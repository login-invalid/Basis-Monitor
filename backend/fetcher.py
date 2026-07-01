"""
股指期货四合约升贴水数据采集模块
支持全量初始化和增量更新。
"""
import akshare as ak
import pandas as pd
import numpy as np
import datetime
import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

PRODUCTS = {
    'IF': {'name': '沪深300', 'spot_symbol': 'sh000300'},
    'IH': {'name': '上证50',  'spot_symbol': 'sh000016'},
    'IC': {'name': '中证500', 'spot_symbol': 'sh000905'},
    'IM': {'name': '中证1000','spot_symbol': 'sh000852'},
}

QUARTER_MONTHS = [3, 6, 9, 12]
MIN_DAYS_FOR_ANNUAL = 5
LOOKBACK_YEARS = 3


# ============================================================
# 合约滚动逻辑
# ============================================================
def get_third_friday(year, month):
    """获取某年某月的第三个星期五（合约到期日）"""
    d = datetime.date(year, month, 1)
    while d.weekday() != 4:
        d += datetime.timedelta(days=1)
    d += datetime.timedelta(weeks=2)
    return d


def get_next_two_quarter_months(after_year, after_month):
    """获取给定年月之后的最近两个季月"""
    quarters = []
    y, m = after_year, after_month
    while len(quarters) < 2:
        m += 1
        if m > 12:
            m = 1
            y += 1
        if m in QUARTER_MONTHS:
            quarters.append((y, m))
    return quarters


def get_active_contracts(date, product):
    """根据日期确定四合约代码（CFFEX规则）"""
    year, month = date.year, date.month
    third_friday = get_third_friday(year, month)

    if date.date() > third_friday:
        if month == 12:
            cm_year, cm_month = year + 1, 1
        else:
            cm_year, cm_month = year, month + 1
    else:
        cm_year, cm_month = year, month

    if cm_month == 12:
        nm_year, nm_month = cm_year + 1, 1
    else:
        nm_year, nm_month = cm_year, cm_month + 1

    q = get_next_two_quarter_months(nm_year, nm_month)
    code = lambda y, mo: f"{product}{y % 100:02d}{mo:02d}"
    return {
        '当月': code(cm_year, cm_month),
        '下月': code(nm_year, nm_month),
        '当季': code(q[0][0], q[0][1]),
        '隔季': code(q[1][0], q[1][1]),
    }


def contract_expiry_date(contract_code):
    """从合约代码解析到期日"""
    yy = int(contract_code[-4:-2])
    mo = int(contract_code[-2:])
    year = 2000 + yy
    return get_third_friday(year, mo)


# ============================================================
# 数据获取
# ============================================================
def fetch_spot(symbol, retries=3):
    """获取现货指数日线"""
    for attempt in range(retries):
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            return df[['close']].rename(columns={'close': 'spot_close'})
        except Exception as e:
            logger.warning(f"获取现货 {symbol} 失败 (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def fetch_futures(contract, retries=3):
    """获取期货合约日线"""
    for attempt in range(retries):
        try:
            df = ak.futures_zh_daily_sina(symbol=contract)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            return contract, df[['close']].rename(columns={'close': 'fut_close'})
        except Exception as e:
            if attempt == retries - 1:
                logger.warning(f"获取期货 {contract} 失败: {e}")
            time.sleep(1)
    return contract, None


# ============================================================
# 基差计算
# ============================================================
def compute_basis_for_dates(spot_df, dates, product, futures_data):
    """为给定日期列表计算基差，返回 records 列表"""
    records = []
    for date in dates:
        contracts = get_active_contracts(date, product)
        if date not in spot_df.index:
            continue
        spot_price = float(spot_df.loc[date, 'spot_close'])
        row = {'date': date.strftime('%Y-%m-%d'), 'spot': round(spot_price, 3)}

        for label in ['当月', '下月', '当季', '隔季']:
            code = contracts[label]
            fut_df = futures_data.get(code)
            if fut_df is not None and date in fut_df.index:
                fut_price = float(fut_df.loc[date, 'fut_close'])
                basis = spot_price - fut_price
                basis_rate = basis / spot_price * 100

                expiry = contract_expiry_date(code)
                days_to_expiry = (expiry - date.date()).days
                if days_to_expiry > 0:
                    annualized = basis_rate * 365 / days_to_expiry
                else:
                    annualized = 0.0

                annual_display = annualized if days_to_expiry >= MIN_DAYS_FOR_ANNUAL else None

                row[f'{label}_code'] = code
                row[f'{label}_price'] = round(fut_price, 2)
                row[f'{label}_basis'] = round(basis, 2)
                row[f'{label}_rate'] = round(basis_rate, 4)
                row[f'{label}_annual'] = round(annual_display, 4) if annual_display is not None else None
                row[f'{label}_days'] = days_to_expiry
            else:
                row[f'{label}_code'] = code
                row[f'{label}_price'] = None
                row[f'{label}_basis'] = None
                row[f'{label}_rate'] = None
                row[f'{label}_annual'] = None
                row[f'{label}_days'] = None

        records.append(row)
    return records


def build_output(records_map, spot_data, trading_dates, validation_results):
    """从 records 构建完整输出 JSON"""
    output = {'products': {}, 'meta': {}, 'validation': validation_results}

    for product, info in PRODUCTS.items():
        records = records_map.get(product, [])
        if not records:
            continue

        df_result = pd.DataFrame(records)

        # 找最新完整数据日
        latest_idx = None
        for i in range(len(df_result) - 1, -1, -1):
            row = df_result.iloc[i]
            if pd.notna(row.get('当月_price')) and pd.notna(row.get('下月_price')) \
               and pd.notna(row.get('当季_price')) and pd.notna(row.get('隔季_price')):
                latest_idx = i
                break
        if latest_idx is None:
            latest_idx = len(df_result) - 1

        latest = df_result.iloc[latest_idx]
        current = {
            'date': latest['date'],
            'spot_price': latest['spot'],
            'contracts': {}
        }
        for label in ['当月', '下月', '当季', '隔季']:
            current['contracts'][label] = {
                'code': latest.get(f'{label}_code', ''),
                'price': latest.get(f'{label}_price'),
                'basis': latest.get(f'{label}_basis'),
                'basis_rate': latest.get(f'{label}_rate'),
                'annualized_rate': latest.get(f'{label}_annual'),
                'days_to_expiry': latest.get(f'{label}_days'),
            }

        # 历史序列
        history = {
            'dates': df_result['date'].tolist(),
            'spot': [None if pd.isna(x) else round(float(x), 2) for x in df_result['spot']],
        }
        for label in ['当月', '下月', '当季', '隔季']:
            history[f'{label}_rate'] = [None if pd.isna(x) else float(x) for x in df_result[f'{label}_rate']]
            history[f'{label}_annual'] = [None if pd.isna(x) else float(x) for x in df_result[f'{label}_annual']]
            history[f'{label}_basis'] = [None if pd.isna(x) else float(x) for x in df_result[f'{label}_basis']]

        # 统计
        stats = {}
        for label in ['当月', '下月', '当季', '隔季']:
            col = df_result[f'{label}_rate'].dropna()
            col_ann = df_result[f'{label}_annual'].dropna()
            if len(col) > 0:
                stats[label] = {
                    'mean': round(float(col.mean()), 4),
                    'std': round(float(col.std()), 4),
                    'min': round(float(col.min()), 4),
                    'max': round(float(col.max()), 4),
                    'latest': round(float(col.iloc[-1]), 4),
                    'pct_positive': round(float((col > 0).mean() * 100), 1),
                }
                if len(col_ann) > 0:
                    stats[label]['ann_mean'] = round(float(col_ann.mean()), 4)
                    stats[label]['ann_std'] = round(float(col_ann.std()), 4)
                    stats[label]['ann_min'] = round(float(col_ann.min()), 4)
                    stats[label]['ann_max'] = round(float(col_ann.max()), 4)
                    stats[label]['ann_latest'] = round(float(col_ann.iloc[-1]), 4) if pd.notna(col_ann.iloc[-1]) else None
                else:
                    for k in ['ann_mean', 'ann_std', 'ann_min', 'ann_max', 'ann_latest']:
                        stats[label][k] = None
            else:
                stats[label] = None

        output['products'][product] = {
            'name': info['name'],
            'current': current,
            'history': history,
            'stats': stats,
        }

    if len(trading_dates) > 0:
        output['meta'] = {
            'generated_at': datetime.date.today().strftime('%Y-%m-%d'),
            'data_start': trading_dates[0].strftime('%Y-%m-%d'),
            'data_end': trading_dates[-1].strftime('%Y-%m-%d'),
            'trading_days': len(trading_dates),
            'source': 'akshare (新浪财经)',
            'convention': '基差 = 现货 - 期货; 正=贴水, 负=升水',
            'lookback_years': LOOKBACK_YEARS,
            'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    return output


# ============================================================
# 全量初始化
# ============================================================
def full_fetch():
    """全量拉取近3年数据"""
    today = datetime.date.today()
    start_date = pd.Timestamp(today.replace(year=today.year - LOOKBACK_YEARS))

    logger.info(f"全量拉取: {start_date.date()} ~ {today}")

    # 获取现货
    spot_data = {}
    for code, info in PRODUCTS.items():
        logger.info(f"  获取现货 {info['name']} ({info['spot_symbol']})...")
        df = fetch_spot(info['spot_symbol'])
        if df is not None:
            df = df.loc[start_date:today]
            spot_data[code] = df
            logger.info(f"    ✓ {len(df)} 条")

    trading_dates = spot_data['IF'].index if 'IF' in spot_data else []
    if len(trading_dates) == 0:
        raise RuntimeError("无法获取现货数据")

    # 确定所需合约
    needed_contracts = set()
    for product in PRODUCTS:
        for date in trading_dates:
            contracts = get_active_contracts(date, product)
            needed_contracts.update(contracts.values())
    needed_contracts = sorted(needed_contracts)
    logger.info(f"  所需合约: {len(needed_contracts)} 个")

    # 并行获取期货
    futures_data = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_futures, c): c for c in needed_contracts}
        for future in as_completed(futures):
            contract = futures[future]
            try:
                result = future.result()
                if result and result[1] is not None:
                    futures_data[result[0]] = result[1]
            except Exception as e:
                logger.warning(f"  ✗ {contract}: {e}")
    logger.info(f"  成功获取 {len(futures_data)}/{len(needed_contracts)} 个合约")

    # 计算基差
    records_map = {}
    validation_results = {}
    for product in PRODUCTS:
        if product not in spot_data:
            continue
        spot_df = spot_data[product]
        dates = spot_df.index
        records = compute_basis_for_dates(spot_df, dates, product, futures_data)
        records_map[product] = records

        missing = {}
        df_tmp = pd.DataFrame(records)
        for label in ['当月', '下月', '当季', '隔季']:
            miss = int(df_tmp[f'{label}_price'].isna().sum())
            missing[label] = f'{miss} ({miss/len(df_tmp)*100:.1f}%)' if len(df_tmp) > 0 else '0 (0%)'
        validation_results[product] = {
            'total_days': len(records),
            'missing': missing,
        }
        logger.info(f"  {product}: {len(records)} 条, 缺失: {missing}")

    return build_output(records_map, spot_data, trading_dates, validation_results)


# ============================================================
# 增量更新
# ============================================================
def incremental_fetch(existing_data):
    """增量更新：只拉取已有数据之后的新数据"""
    if not existing_data or 'meta' not in existing_data or 'data_end' not in existing_data['meta']:
        logger.info("无已有数据，执行全量拉取")
        return full_fetch()

    old_end_str = existing_data['meta']['data_end']
    old_end = pd.Timestamp(old_end_str)
    today = datetime.date.today()

    # 如果已有数据已经是今天，不需要更新
    if old_end.date() >= today:
        logger.info(f"数据已是最新 ({old_end_str})，无需更新")
        return existing_data

    logger.info(f"增量更新: {old_end_str} → {today}")

    # 保留旧数据起始日，但滑动窗口保持3年
    start_date = pd.Timestamp(today.replace(year=today.year - LOOKBACK_YEARS))

    # 获取现货（全量拉取再截取，现货数据量不大）
    spot_data = {}
    for code, info in PRODUCTS.items():
        logger.info(f"  获取现货 {info['name']}...")
        df = fetch_spot(info['spot_symbol'])
        if df is not None:
            df = df.loc[start_date:today]
            spot_data[code] = df

    trading_dates = spot_data['IF'].index if 'IF' in spot_data else []
    if len(trading_dates) == 0:
        logger.warning("增量更新无法获取现货数据，返回旧数据")
        return existing_data

    # 确定所需合约
    needed_contracts = set()
    for product in PRODUCTS:
        for date in trading_dates:
            contracts = get_active_contracts(date, product)
            needed_contracts.update(contracts.values())
    needed_contracts = sorted(needed_contracts)

    # 并行获取期货
    futures_data = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_futures, c): c for c in needed_contracts}
        for future in as_completed(futures):
            contract = futures[future]
            try:
                result = future.result()
                if result and result[1] is not None:
                    futures_data[result[0]] = result[1]
            except Exception as e:
                logger.warning(f"  ✗ {contract}: {e}")
    logger.info(f"  成功获取 {len(futures_data)}/{len(needed_contracts)} 个合约")

    # 计算基差
    records_map = {}
    validation_results = {}
    for product in PRODUCTS:
        if product not in spot_data:
            continue
        spot_df = spot_data[product]
        dates = spot_df.index
        records = compute_basis_for_dates(spot_df, dates, product, futures_data)
        records_map[product] = records

        missing = {}
        df_tmp = pd.DataFrame(records)
        for label in ['当月', '下月', '当季', '隔季']:
            miss = int(df_tmp[f'{label}_price'].isna().sum())
            missing[label] = f'{miss} ({miss/len(df_tmp)*100:.1f}%)' if len(df_tmp) > 0 else '0 (0%)'
        validation_results[product] = {
            'total_days': len(records),
            'missing': missing,
        }

    return build_output(records_map, spot_data, trading_dates, validation_results)
