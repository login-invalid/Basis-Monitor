/**
 * 纯前端数据获取模块
 * 通过 CORS 代理从东方财富获取现货指数与期货合约日K线数据，
 * 在浏览器端完成基差计算，无需 Python 后端。
 */
var BasisAPI = (function() {
  'use strict';

  // ---- 配置 ----
  var PRODUCTS = {
    IF: { name: '沪深300',  spotSecid: '1.000300' },
    IH: { name: '上证50',   spotSecid: '1.000016' },
    IC: { name: '中证500',  spotSecid: '1.000905' },
    IM: { name: '中证1000', spotSecid: '1.000852' }
  };
  var LABELS = ['当月','下月','当季','隔季'];
  var QUARTER_MONTHS = [3,6,9,12];
  var MIN_DAYS_FOR_ANNUAL = 5;

  // CORS 代理列表（按优先级尝试，第一个成功即用）
  var CORS_PROXIES = [
    'https://corsproxy.io/?url=',
    'https://api.allorigins.win/raw?url='
  ];

  // ---- 工具函数 ----
  function fmt(v, d) { d = d || 2; return v == null ? null : Number(v).toFixed(d); }

  function getThirdFriday(year, month) {
    var d = new Date(year, month - 1, 1);
    while (d.getDay() !== 5) d.setDate(d.getDate() + 1);
    d.setDate(d.getDate() + 14);
    return d;
  }

  function getNextTwoQuarterMonths(afterYear, afterMonth) {
    var quarters = [], y = afterYear, m = afterMonth;
    while (quarters.length < 2) {
      m++;
      if (m > 12) { m = 1; y++; }
      if (QUARTER_MONTHS.indexOf(m) !== -1) quarters.push([y, m]);
    }
    return quarters;
  }

  function getActiveContracts(date, product) {
    var year = date.getFullYear(), month = date.getMonth() + 1;
    var thirdFriday = getThirdFriday(year, month);
    var cmYear, cmMonth;
    if (date > thirdFriday) {
      cmYear = month === 12 ? year + 1 : year;
      cmMonth = month === 12 ? 1 : month + 1;
    } else {
      cmYear = year; cmMonth = month;
    }
    var nmYear = cmMonth === 12 ? cmYear + 1 : cmYear;
    var nmMonth = cmMonth === 12 ? 1 : cmMonth + 1;
    var q = getNextTwoQuarterMonths(nmYear, nmMonth);
    function code(y, mo) { return product + String(y % 100).padStart(2, '0') + String(mo).padStart(2, '0'); }
    return { '当月': code(cmYear, cmMonth), '下月': code(nmYear, nmMonth), '当季': code(q[0][0], q[0][1]), '隔季': code(q[1][0], q[1][1]) };
  }

  function contractExpiryDate(contractCode) {
    var yy = parseInt(contractCode.substring(2, 4), 10);
    var mo = parseInt(contractCode.substring(4, 6), 10);
    return getThirdFriday(2000 + yy, mo);
  }

  function parseDate(s) {
    var parts = s.split('-');
    return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
  }

  function dateStr(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // ---- 带重试的 CORS 代理 fetch ----
  function proxyFetch(url, retries) {
    retries = retries || CORS_PROXIES.length;
    var idx = 0;
    function tryNext() {
      if (idx >= retries) return Promise.reject(new Error('所有CORS代理均不可用'));
      var proxyUrl = CORS_PROXIES[idx] + encodeURIComponent(url);
      return fetch(proxyUrl, { signal: AbortSignal.timeout(15000) }).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r;
      }).catch(function() {
        idx++;
        return tryNext();
      });
    }
    return tryNext();
  }

  // ---- 获取现货指数日K线 (东方财富) ----
  function fetchSpotKline(secid, startDate) {
    var url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
      + '?secid=' + secid
      + '&fields1=f1,f2,f3,f4,f5,f6'
      + '&fields2=f51,f52,f53,f54,f55,f56,f57'
      + '&klt=101&fqt=1'
      + '&beg=' + startDate.replace(/-/g, '')
      + '&end=20500101&lmt=2000';
    return proxyFetch(url).then(function(r) { return r.json(); }).then(function(json) {
      if (!json || !json.data || !json.data.klines) return {};
      var map = {};
      json.data.klines.forEach(function(line) {
        var parts = line.split(',');
        map[parts[0]] = parseFloat(parts[2]); // close
      });
      return map;
    });
  }

  // ---- 获取期货合约日K线 (东方财富) ----
  function fetchFuturesKline(contractCode, startDate) {
    var emCode = '8.' + contractCode;
    var url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
      + '?secid=' + emCode
      + '&fields1=f1,f2,f3,f4,f5,f6'
      + '&fields2=f51,f52,f53,f54,f55,f56,f57'
      + '&klt=101&fqt=1'
      + '&beg=' + startDate.replace(/-/g, '')
      + '&end=20500101&lmt=2000';
    return proxyFetch(url).then(function(r) { return r.json(); }).then(function(json) {
      if (!json || !json.data || !json.data.klines) return {};
      var map = {};
      json.data.klines.forEach(function(line) {
        var parts = line.split(',');
        map[parts[0]] = parseFloat(parts[2]);
      });
      return map;
    });
  }

  // ---- 核心逻辑：获取增量数据并计算基差 ----
  function fetchIncremental(existingData) {
    var today = new Date();
    var oldEnd = null;
    if (existingData && existingData.meta && existingData.meta.data_end) {
      oldEnd = parseDate(existingData.meta.data_end);
    }
    // 如果数据已经是今天或周末，不需要更新，但仍刷新时间戳
    if (oldEnd && (dateStr(oldEnd) >= dateStr(today) || today.getDay() === 0 || today.getDay() === 6)) {
      var result = JSON.parse(JSON.stringify(existingData));
      result.meta.last_updated = new Date().toLocaleString('zh-CN', {hour12: false});
      return Promise.resolve(result);
    }

    var startDate = oldEnd ? dateStr(oldEnd) : dateStr(new Date(today.getFullYear() - 3, today.getMonth(), today.getDate()));
    // 从旧数据结束日前一天开始拉取，确保不丢失边界日
    if (oldEnd) {
      oldEnd.setDate(oldEnd.getDate() - 1);
      startDate = dateStr(oldEnd);
    }

    // 1. 获取所有现货数据
    var spotPromises = {};
    Object.keys(PRODUCTS).forEach(function(p) {
      spotPromises[p] = fetchSpotKline(PRODUCTS[p].spotSecid, startDate);
    });

    return Promise.all(Object.values(spotPromises)).then(function(spotResults) {
      var spotData = {};
      var keys = Object.keys(PRODUCTS);
      keys.forEach(function(p, i) { spotData[p] = spotResults[i]; });

      var ifDates = Object.keys(spotData['IF'] || {}).sort();
      if (ifDates.length === 0) throw new Error('无法获取现货数据，请检查网络连接');

      // 2. 确定所需合约
      var neededContracts = {};
      keys.forEach(function(product) {
        ifDates.forEach(function(dStr) {
          var d = parseDate(dStr);
          var contracts = getActiveContracts(d, product);
          LABELS.forEach(function(l) { neededContracts[contracts[l]] = true; });
        });
      });

      // 3. 并行获取期货数据
      var contractList = Object.keys(neededContracts);
      var fetchPromises = contractList.map(function(c) {
        return fetchFuturesKline(c, startDate).then(function(data) {
          return { code: c, data: data };
        });
      });

      return Promise.all(fetchPromises).then(function(futuresResults) {
        var futuresData = {};
        futuresResults.forEach(function(r) { futuresData[r.code] = r.data; });
        return mergeAndCompute(existingData, spotData, futuresData, ifDates);
      });
    });
  }

  // ---- 合并增量数据到已有 dataset ----
  function mergeAndCompute(existingData, spotData, futuresData, newDates) {
    var existingEndDate = existingData && existingData.meta && existingData.meta.data_end
      ? existingData.meta.data_end : '2000-01-01';

    var newRecords = {};
    Object.keys(PRODUCTS).forEach(function(product) {
      newRecords[product] = [];
      var spot = spotData[product] || {};
      newDates.forEach(function(dStr) {
        if (dStr <= existingEndDate) return;
        var spotPrice = spot[dStr];
        if (!spotPrice) return;
        var d = parseDate(dStr);
        var contracts = getActiveContracts(d, product);
        var row = { date: dStr, spot: spotPrice };
        LABELS.forEach(function(l) {
          var code = contracts[l];
          var futPrice = (futuresData[code] || {})[dStr];
          if (futPrice != null) {
            var basis = spotPrice - futPrice;
            var basisRate = basis / spotPrice * 100;
            var expiry = contractExpiryDate(code);
            var daysToExpiry = Math.round((expiry - d) / 86400000);
            var annualized = daysToExpiry >= MIN_DAYS_FOR_ANNUAL ? basisRate * 365 / daysToExpiry : null;
            row[l + '_code'] = code;
            row[l + '_price'] = futPrice;
            row[l + '_basis'] = basis;
            row[l + '_rate'] = basisRate;
            row[l + '_annual'] = annualized;
            row[l + '_days'] = daysToExpiry;
          } else {
            row[l + '_code'] = code;
            row[l + '_price'] = null;
            row[l + '_basis'] = null;
            row[l + '_rate'] = null;
            row[l + '_annual'] = null;
            row[l + '_days'] = null;
          }
        });
        newRecords[product].push(row);
      });
    });

    var hasNew = Object.values(newRecords).some(function(recs) { return recs.length > 0; });
    var output = JSON.parse(JSON.stringify(existingData));
    output.meta.last_updated = new Date().toLocaleString('zh-CN', {hour12: false});

    if (!hasNew) {
      return output;
    }

    Object.keys(PRODUCTS).forEach(function(p) {
      var pd = output.products[p];
      if (!pd) return;
      LABELS.forEach(function(l) {
        if (!pd.history[l + '_price']) {
          pd.history[l + '_price'] = new Array(pd.history.dates.length).fill(null);
        }
        if (!pd.history[l + '_basis']) {
          pd.history[l + '_basis'] = new Array(pd.history.dates.length).fill(null);
        }
      });
      var recs = newRecords[p];
      recs.forEach(function(row) {
        pd.history.dates.push(row.date);
        pd.history.spot.push(row.spot);
        LABELS.forEach(function(l) {
          pd.history[l + '_rate'].push(row[l + '_rate']);
          pd.history[l + '_annual'].push(row[l + '_annual']);
          pd.history[l + '_basis'].push(row[l + '_basis']);
          pd.history[l + '_price'].push(row[l + '_price']);
        });
      });

      // 更新 current 为最后一条完整数据
      for (var i = pd.history.dates.length - 1; i >= 0; i--) {
        if (pd.history['当月_rate'][i] != null && pd.history['下月_rate'][i] != null
            && pd.history['当季_rate'][i] != null && pd.history['隔季_rate'][i] != null
            && pd.history.spot[i] != null) {
          var date = pd.history.dates[i];
          var spotPrice = pd.history.spot[i];
          pd.current = { date: date, spot_price: spotPrice, contracts: {} };
          LABELS.forEach(function(l) {
            var code = null, days = null, price = null, basis = null, rate = null, annual = null;
            for (var j = recs.length - 1; j >= 0; j--) {
              if (recs[j].date === date) {
                code = recs[j][l + '_code'];
                days = recs[j][l + '_days'];
                price = recs[j][l + '_price'];
                break;
              }
            }
            if (!code && pd.current && pd.current.contracts && pd.current.contracts[l]) {
              code = pd.current.contracts[l].code;
            }
            rate = pd.history[l + '_rate'][i];
            annual = pd.history[l + '_annual'][i];
            basis = pd.history[l + '_basis'][i];
            if (!price && spotPrice != null && rate != null) {
              basis = spotPrice * rate / 100;
            }
            pd.current.contracts[l] = {
              code: code || '',
              price: price || (spotPrice != null && rate != null ? parseFloat((spotPrice - basis).toFixed(2)) : null),
              basis: basis != null ? parseFloat(basis.toFixed(2)) : null,
              basis_rate: rate != null ? parseFloat(rate.toFixed(4)) : null,
              annualized_rate: annual != null ? parseFloat(annual.toFixed(4)) : null,
              days_to_expiry: days
            };
          });
          break;
        }
      }

      pd.stats = recalcStats(pd.history);
    });

    // data_end 与 current.date 保持一致（而非 history 末尾）
    var currentDate = null;
    Object.keys(PRODUCTS).forEach(function(p) {
      if (output.products[p] && output.products[p].current && output.products[p].current.date) {
        if (!currentDate || output.products[p].current.date > currentDate) currentDate = output.products[p].current.date;
      }
    });
    if (currentDate) output.meta.data_end = currentDate;
    if (output.products.IF && output.products.IF.history && output.products.IF.history.dates) {
      output.meta.trading_days = output.products.IF.history.dates.length;
    }

    return output;
  }

  // ---- 重新统计 ----
  function recalcStats(history) {
    var stats = {};
    LABELS.forEach(function(l) {
      var col = history[l + '_rate'] || [];
      var colAnn = history[l + '_annual'] || [];
      var valid = col.filter(function(v) { return v != null; });
      var validAnn = colAnn.filter(function(v) { return v != null; });
      if (valid.length > 0) {
        var sum = valid.reduce(function(a, b) { return a + b; }, 0);
        var mean = sum / valid.length;
        var variance = valid.reduce(function(a, b) { return a + (b - mean) * (b - mean); }, 0) / valid.length;
        var annSum = 0, annMin = Infinity, annMax = -Infinity;
        validAnn.forEach(function(v) { annSum += v; if (v < annMin) annMin = v; if (v > annMax) annMax = v; });
        var latest = valid[valid.length - 1];
        var positiveCount = valid.filter(function(v) { return v > 0; }).length;
        stats[l] = {
          mean: parseFloat(mean.toFixed(4)),
          std: parseFloat(Math.sqrt(variance).toFixed(4)),
          min: parseFloat(Math.min.apply(null, valid).toFixed(4)),
          max: parseFloat(Math.max.apply(null, valid).toFixed(4)),
          latest: parseFloat(latest.toFixed(4)),
          pct_positive: parseFloat((positiveCount / valid.length * 100).toFixed(1)),
          ann_mean: validAnn.length > 0 ? parseFloat((annSum / validAnn.length).toFixed(4)) : null,
          ann_std: null,
          ann_min: validAnn.length > 0 ? parseFloat(annMin.toFixed(4)) : null,
          ann_max: validAnn.length > 0 ? parseFloat(annMax.toFixed(4)) : null,
          ann_latest: validAnn.length > 0 ? parseFloat(validAnn[validAnn.length - 1].toFixed(4)) : null
        };
      } else {
        stats[l] = null;
      }
    });
    return stats;
  }

  // ---- 增量更新入口 ----
  function incrementalUpdate(existingData) {
    return fetchIncremental(existingData).then(function(newData) {
      window.basisData = newData;
      return newData;
    });
  }

  return {
    incrementalUpdate: incrementalUpdate
  };
})();