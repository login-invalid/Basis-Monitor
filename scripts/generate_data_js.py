"""
自动更新 data.js 的脚本，供 GitHub Actions 使用。
逻辑与 backend/fetcher.py 一致，输出格式与 frontend/assets/data.js 兼容。
"""
import json
import datetime
import time
import logging
import akshare as ak
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

PRODUCTS = {
    'IF': {'name': '沪深300', 'spot_symbol': 'sh000300'},
    'IH': {'name': '上证50', 'spot_symbol': 'sh000016'},
    'IC': {'name': '中证500', 'spot_symbol': 'sh000905'},
    'IM': {'name': '中证1000', 'spot_symbol': 'sh000852'},
}
LABELS = ['当月', '下月', '当季', '隔季']
QUARTER_MONTHS = [3, 6, 9, 12]
MIN_DAYS_FOR_ANNUAL = 5
LOOKBACK_YEARS = 3
OUTPUT_PATH = 'frontend/assets/data.js'


def get_third_friday(year, month):
    d = datetime.date(year, month, 1)
    while d.weekday() != 4:
        d += datetime.timedelta(days=1)
    d += datetime.timedelta(weeks=2)
    return d


def get_next_two_quarter_months(after_year, after_month):
    quarters, y, m = [], after_year, after_month
    while len(quarters) < 2:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        if m in QUARTER_MONTHS:
            quarters.append((y, m))
    return quarters


def get_active_contracts(date, product):
    d = date.date() if hasattr(date, 'date') else date
    year, month = d.year, d.month
    tf = get_third_friday(year, month)
    if d > tf:
        cm_year, cm_month = (year + 1, 1) if month == 12 else (year, month + 1)
    else:
        cm_year, cm_month = year, month
    nm_year = cm_year + 1 if cm_month == 12 else cm_year
    nm_month = 1 if cm_month == 12 else cm_month + 1
    q = get_next_two_quarter_months(nm_year, nm_month)
    code = lambda y, mo: f"{product}{y % 100:02d}{mo:02d}"
    return {'当月': code(cm_year, cm_month), '下月': code(nm_year, nm_month),
            '当季': code(q[0][0], q[0][1]), '隔季': code(q[1][0], q[1][1])}


def contract_expiry_date(contract_code):
    yy, mo = int(contract_code[2:4]), int(contract_code[4:6])
    return get_third_friday(2000 + yy, mo)


def fetch_spot(symbol, retries=3):
    for attempt in range(retries):
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            return df[['close']].rename(columns={'close': 'spot_close'})
        except Exception as e:
            logger.warning(f"现货 {symbol} 失败 ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None


def fetch_futures(contract, retries=3):
    for attempt in range(retries):
        try:
            df = ak.futures_zh_daily_sina(symbol=contract)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            return contract, df[['close']].rename(columns={'close': 'fut_close'})
        except Exception as e:
            if attempt == retries - 1:
                logger.warning(f"期货 {contract} 失败: {e}")
            time.sleep(1)
    return contract, None


def compute_basis(spot_df, dates, product, futures_data):
    records = []
    for date in dates:
        contracts = get_active_contracts(date, product)
        if date not in spot_df.index:
            continue
        spot_price = float(spot_df.loc[date, 'spot_close'])
        row = {'date': date.strftime('%Y-%m-%d'), 'spot': round(spot_price, 3)}
        for label in LABELS:
            code = contracts[label]
            fut_df = futures_data.get(code)
            if fut_df is not None and date in fut_df.index:
                fut_price = float(fut_df.loc[date, 'fut_close'])
                basis = spot_price - fut_price
                basis_rate = basis / spot_price * 100
                expiry = contract_expiry_date(code)
                days = (expiry - date.date()).days
                annual = basis_rate * 365 / days if days >= MIN_DAYS_FOR_ANNUAL else None
                row[f'{label}_code'] = code
                row[f'{label}_price'] = round(fut_price, 2)
                row[f'{label}_basis'] = round(basis, 2)
                row[f'{label}_rate'] = round(basis_rate, 4)
                row[f'{label}_annual'] = round(annual, 4) if annual is not None else None
                row[f'{label}_days'] = days
            else:
                for suffix in ['_code', '_price', '_basis', '_rate', '_annual', '_days']:
                    row[f'{label}{suffix}'] = code if suffix == '_code' else None
        records.append(row)
    return records


def build_output(records_map, spot_data, trading_dates, validation):
    output = {'products': {}, 'meta': {}, 'validation': validation}
    for product, info in PRODUCTS.items():
        records = records_map.get(product, [])
        if not records:
            continue
        df_result = pd.DataFrame(records)
        latest_idx = None
        for i in range(len(df_result) - 1, -1, -1):
            row = df_result.iloc[i]
            if all(pd.notna(row.get(f'{l}_price')) for l in LABELS):
                latest_idx = i
                break
        if latest_idx is None:
            latest_idx = len(df_result) - 1
        latest = df_result.iloc[latest_idx]
        current = {'date': latest['date'], 'spot_price': latest['spot'], 'contracts': {}}
        for label in LABELS:
            current['contracts'][label] = {
                'code': latest.get(f'{label}_code', ''),
                'price': float(latest[f'{label}_price']) if pd.notna(latest.get(f'{label}_price')) else None,
                'basis': float(latest[f'{label}_basis']) if pd.notna(latest.get(f'{label}_basis')) else None,
                'basis_rate': float(latest[f'{label}_rate']) if pd.notna(latest.get(f'{label}_rate')) else None,
                'annualized_rate': float(latest[f'{label}_annual']) if pd.notna(latest.get(f'{label}_annual')) else None,
                'days_to_expiry': int(latest[f'{label}_days']) if pd.notna(latest.get(f'{label}_days')) else None,
            }
        history = {
            'dates': df_result['date'].tolist(),
            'spot': [None if pd.isna(x) else round(float(x), 2) for x in df_result['spot']],
        }
        for label in LABELS:
            for field, suffix in [('_rate', '_rate'), ('_annual', '_annual'), ('_basis', '_basis')]:
                history[f'{label}{suffix}'] = [
                    None if pd.isna(x) else float(x) for x in df_result[f'{label}{suffix}']
                ]
        stats = {}
        for label in LABELS:
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
                    stats[label].update({
                        'ann_mean': round(float(col_ann.mean()), 4),
                        'ann_std': round(float(col_ann.std()), 4),
                        'ann_min': round(float(col_ann.min()), 4),
                        'ann_max': round(float(col_ann.max()), 4),
                        'ann_latest': round(float(col_ann.iloc[-1]), 4) if pd.notna(col_ann.iloc[-1]) else None,
                    })
                else:
                    for k in ['ann_mean', 'ann_std', 'ann_min', 'ann_max', 'ann_latest']:
                        stats[label][k] = None
            else:
                stats[label] = None
        output['products'][product] = {
            'name': info['name'], 'current': current, 'history': history, 'stats': stats,
        }
    if len(trading_dates) > 0:
        output['meta'] = {
            'generated_at': datetime.date.today().strftime('%Y-%m-%d'),
            'data_start': trading_dates[0].strftime('%Y-%m-%d'),
            'data_end': trading_dates[-1].strftime('%Y-%m-%d'),
            'trading_days': len(trading_dates),
            'source': 'akshare',
            'convention': '基差 = 现货 - 期货; 正=贴水, 负=升水',
            'lookback_years': LOOKBACK_YEARS,
            'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    return output


def main():
    logger.info("=== 开始全量数据拉取 ===")
    today = pd.Timestamp(datetime.date.today())
    start_date = pd.Timestamp(today.date().replace(year=today.year - LOOKBACK_YEARS))

    # 获取现货
    spot_data = {}
    for code, info in PRODUCTS.items():
        logger.info(f"获取现货 {info['name']} ({info['spot_symbol']})...")
        df = fetch_spot(info['spot_symbol'])
        if df is not None:
            df = df.loc[start_date:today]
            spot_data[code] = df
            logger.info(f"  {len(df)} 条")

    trading_dates = spot_data['IF'].index if 'IF' in spot_data else []
    if len(trading_dates) == 0:
        raise RuntimeError("无法获取现货数据")

    # 确定合约
    needed = set()
    for product in PRODUCTS:
        for date in trading_dates:
            contracts = get_active_contracts(date, product)
            needed.update(contracts.values())
    needed = sorted(needed)
    logger.info(f"所需合约: {len(needed)} 个")

    # 并行获取期货
    futures_data = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_futures, c): c for c in needed}
        for future in as_completed(futures):
            contract = futures[future]
            try:
                result = future.result()
                if result and result[1] is not None:
                    futures_data[result[0]] = result[1]
            except Exception as e:
                logger.warning(f"  {contract}: {e}")
    logger.info(f"成功: {len(futures_data)}/{len(needed)} 个合约")

    # 计算
    records_map, validation = {}, {}
    for product in PRODUCTS:
        if product not in spot_data:
            continue
        dates = spot_data[product].index
        records = compute_basis(spot_data[product], dates, product, futures_data)
        records_map[product] = records
        missing = {}
        df_tmp = pd.DataFrame(records)
        for label in LABELS:
            miss = int(df_tmp[f'{label}_price'].isna().sum())
            missing[label] = f'{miss} ({miss/len(df_tmp)*100:.1f}%)' if len(df_tmp) > 0 else '0 (0%)'
        validation[product] = {'total_days': len(records), 'missing': missing}
        logger.info(f"{product}: {len(records)} 条, 缺失: {missing}")

    output = build_output(records_map, spot_data, trading_dates, validation)

    # 写入 data.js
    js_content = 'var basisData = ' + json.dumps(output, ensure_ascii=False, separators=(',', ':')) + ';'
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(js_content)
    logger.info(f"已写入 {OUTPUT_PATH} ({len(js_content) // 1024} KB)")


if __name__ == '__main__':
    main()