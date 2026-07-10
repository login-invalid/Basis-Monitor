(function() {
  'use strict';
  var style = getComputedStyle(document.documentElement);
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var pos = style.getPropertyValue('--pos').trim();
  var neg = style.getPropertyValue('--neg').trim();
  var c1 = style.getPropertyValue('--c1').trim();
  var c2 = style.getPropertyValue('--c2').trim();
  var c3 = style.getPropertyValue('--c3').trim();
  var c4 = style.getPropertyValue('--c4').trim();

  var FONT = "Outfit,'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif";
  var PRODUCTS = ['IF','IH','IC','IM'];
  var LABELS = ['当月','下月','当季','隔季'];
  var CC = [c1,c2,c3,c4];
  var PC = {IF:c1,IH:c2,IC:c3,IM:c4};
  var D = window.basisData || null;
  var charts = {};

  function fmt(v,d){d=d||2;return v==null?'—':Number(v).toFixed(d);}
  function fmtP(v,d){d=d||2;return v==null?'—':Number(v).toFixed(d)+'%';}
  function toast(m,t){var e=document.getElementById('toast');if(!e)return;e.className='toast '+(t||'info');e.textContent=m;e.classList.add('show');setTimeout(function(){e.classList.remove('show');},3500);}
  function setStatus(t,d){var te=document.getElementById('status-text');var de=document.getElementById('status-dot');if(te)te.textContent=t;if(de)de.className='status-dot '+(d||'');}

  function getChart(id){
    var el=document.getElementById(id);if(!el)return null;
    if(charts[id]){charts[id].dispose();}
    var c=echarts.init(el,null,{renderer:'svg'});charts[id]=c;
    window.addEventListener('resize',function(){c.resize();});
    return c;
  }

  function updateMeta(){
    if(!D||!D.meta)return;var m=D.meta;
    var r=document.getElementById('badge-range'),d=document.getElementById('badge-days'),u=document.getElementById('badge-updated');
    if(r)r.textContent='数据区间: '+(m.data_start||'?')+' ~ '+(m.data_end||'?');
    if(d)d.textContent='交易日数: '+(m.trading_days||'?');
    if(u)u.textContent='最后更新: '+(m.last_updated||m.generated_at||'?');
    var desc=document.getElementById('overview-desc');
    if(desc&&D.products.IF)desc.textContent='截取最新交易日（'+D.products.IF.current.date+'）数据，展示四大股指期货品种各合约的基差状态。';
  }

  function renderInsights(){
    var el=document.getElementById('insights-list');if(!el||!D||!D.products)return;
    var insights=[];
    // 1. 全面贴水/升贴水分布
    var totalContracts=0,discountContracts=0,premiumContracts=0;
    var discountDetails=[],premiumDetails=[];
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;
      LABELS.forEach(function(l){var r=pd.current.contracts[l];if(!r||r.basis==null)return;
        totalContracts++;
        if(r.basis>0){discountContracts++;discountDetails.push(p+l);}
        else if(r.basis<0){premiumContracts++;premiumDetails.push(p+l);}
      });
    });
    if(discountContracts===totalContracts&&totalContracts>0){
      insights.push('<mark>全面贴水</mark>：截至最新交易日，四大品种所有 '+totalContracts+' 个合约均处于贴水状态。');
    }else if(premiumContracts===totalContracts&&totalContracts>0){
      insights.push('<mark>全面升水</mark>：截至最新交易日，四大品种所有 '+totalContracts+' 个合约均处于升水状态。');
    }else{
      insights.push('<mark>升贴水并存</mark>：截至最新交易日，'+discountContracts+' 个合约贴水（'+discountDetails.join('、')+'），'+premiumContracts+' 个合约升水（'+premiumDetails.join('、')+'）。');
    }
    // 2. 远月加深趋势
    var deepestProduct=null,deepestVal=-Infinity;
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;var st=pd.stats;
      var front=st['当月']?st['当月'].mean:null;
      var back=st['隔季']?st['隔季'].mean:null;
      if(front!=null&&back!=null&&back>deepestVal){deepestVal=back;deepestProduct=p+' '+pd.name;}
    });
    if(deepestProduct){
      var dpD=D.products[deepestProduct.split(' ')[0]];
      var fm=dpD?dpD.stats['当月']:null,bm=dpD?dpD.stats['隔季']:null;
      if(fm&&bm){
        insights.push('<mark>远月加深</mark>：贴水幅度随合约到期日延长系统性递增。以'+deepestProduct+'为例，当月3年均值'+fmt(fm.mean,2)+'% → 隔季'+fmt(bm.mean,2)+'%，远月贴水约为当月的'+(fm.mean!==0?(bm.mean/fm.mean).toFixed(1):'?')+'倍。');
      }
    }
    // 3. 小盘 vs 大盘
    var ifBack=D.products.IF?D.products.IF.stats['隔季']:null;
    var imBack=D.products.IM?D.products.IM.stats['隔季']:null;
    if(ifBack&&imBack&&ifBack.mean!=null&&imBack.mean!=null){
      var ratio=ifBack.mean!==0?(imBack.mean/ifBack.mean).toFixed(1):'?';
      insights.push('<mark>小盘更深</mark>：IM与IC贴水幅度系统性大于IF与IH。IM隔季3年均值'+fmt(imBack.mean,2)+'%，是IF隔季（'+fmt(ifBack.mean,2)+'%）的'+ratio+'倍，反映小盘股更高的分红率与做空对冲需求。');
    }
    // 4. 年化特征
    var annFront=null,annBack=null,annFrontP=null,annBackP=null;
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;var st=pd.stats;
      var fa=st['当月']?st['当月'].ann_mean:null;
      var ba=st['隔季']?st['隔季'].ann_mean:null;
      if(fa!=null&&(annFront==null||fa>annFront)){annFront=fa;annFrontP=p;}
      if(ba!=null&&(annBack==null||ba>annBack)){annBack=ba;annBackP=p;}
    });
    if(annFront!=null&&annBack!=null){
      insights.push('<mark>年化特征</mark>：短期合约年化基差率更高（'+annFrontP+'当月3年均值'+fmt(annFront,2)+'%），远月年化趋于收敛（'+annBackP+'隔季'+fmt(annBack,2)+'%），短期贴水套利空间相对更大。');
    }
    // 5. 贴水天数占比
    var highDiscountPcts=[];
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;
      LABELS.forEach(function(l){var st=pd.stats[l];if(!st)return;
        if(st.pct_positive>90)highDiscountPcts.push(p+l+' '+fmt(st.pct_positive,1)+'%');
      });
    });
    if(highDiscountPcts.length>0){
      insights.push('<mark>贴水常态</mark>：部分合约贴水天数占比超过90%：'+highDiscountPcts.slice(0,4).join('、')+'，贴水为常态现象。');
    }
    el.innerHTML=insights.map(function(t){return '<li>'+t+'</li>';}).join('');
  }

  function renderCards(){
    if(!D)return;var h='';
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;var c=pd.current,fm=c.contracts['当月'];var bs=fm.basis,cl=bs==null?'neutral':(bs>0?'pos':(bs<0?'neg':'neutral')),st=bs==null?'无数据':(bs>0?'贴水':(bs<0?'升水':'平水'));
      h+='<div class="metric-card"><div class="mc-header"><span class="mc-name">'+p+' '+pd.name+'</span><span class="mc-spot">'+fmt(c.spot_price,1)+'</span></div>'
      +'<div class="mc-value '+cl+'">'+fmtP(fm.basis_rate)+'</div><div class="mc-label">当月基差率 · '+fm.code+'</div>'
      +'<span class="mc-status '+cl+'">'+st+'</span><div class="mc-annual">年化: '+fmtP(fm.annualized_rate)+' · 剩余'+(fm.days_to_expiry||'—')+'天</div></div>';});
    var el=document.getElementById('metric-cards');if(el)el.innerHTML=h;
  }

  function renderTable(){
    if(!D)return;var h='';
    PRODUCTS.forEach(function(p){var pd=D.products[p];if(!pd)return;var c=pd.current;
      h+='<tr class="product-row"><td colspan="9">'+p+' '+pd.name+' — 现货: '+fmt(c.spot_price,3)+' · 日期: '+c.date+'</td></tr>';
      LABELS.forEach(function(l){var r=c.contracts[l],bs=r.basis,cl=bs==null?'neutral':(bs>0?'pos':(bs<0?'neg':'neutral')),st=bs==null?'无数据':(bs>0?'贴水':(bs<0?'升水':'平水'));
        h+='<tr><td></td><td>'+l+'</td><td>'+r.code+'</td><td>'+fmt(r.price,1)+'</td><td class="'+cl+'-text">'+fmt(r.basis,2)+'</td><td class="'+cl+'-text">'+fmt(r.basis_rate,2)+'</td><td class="'+cl+'-text">'+fmt(r.annualized_rate,2)+'</td><td>'+(r.days_to_expiry||'—')+'</td><td><span class="status-tag '+cl+'">'+st+'</span></td></tr>';});});
    var el=document.getElementById('snapshot-tbody');if(el)el.innerHTML=h;
  }

  function renderStats(){
    if(!D)return;PRODUCTS.forEach(function(p){var st=D.products[p]?D.products[p].stats:null;if(!st)return;var h='';
      LABELS.forEach(function(l){var s=st[l];if(!s){h+='<tr><td>'+l+'</td><td colspan="8">—</td></tr>';return;}
        h+='<tr><td>'+l+'</td><td>'+fmt(s.mean,2)+'</td><td>'+fmt(s.latest,2)+'</td><td>'+fmt(s.min,2)+'</td><td>'+fmt(s.max,2)+'</td><td>'+fmt(s.pct_positive,1)+'</td><td>'+fmt(s.ann_mean,2)+'</td><td>'+fmt(s.ann_latest,2)+'</td><td>'+fmt(s.ann_min,2)+'</td><td>'+fmt(s.ann_max,2)+'</td></tr>';});
      var el=document.getElementById('stats-'+p.toLowerCase()+'-tbody');if(el)el.innerHTML=h;});
  }

  function lineOpt(dates,sd,yn,ml){
    var s=sd.map(function(x){return{name:x.name,type:'line',data:x.data,showSymbol:false,lineStyle:{width:1.5},itemStyle:{color:x.color},connectNulls:false,emphasis:{focus:'series'}};});
    if(ml&&s.length>0)s[0].markLine={silent:true,symbol:'none',lineStyle:{color:muted,type:'dashed',width:1},data:[{yAxis:0,label:{formatter:'升贴水分界',color:muted,fontFamily:FONT,fontSize:10}}]};
    return{textStyle:{fontFamily:FONT,color:ink},tooltip:{trigger:'axis',appendToBody:true,formatter:function(p){var s=p[0].axisValue+'<br/>';p.forEach(function(x){if(x.value==null)return;var c=x.value>0?pos:(x.value<0?neg:muted);s+=x.marker+x.seriesName+': <b style="color:'+c+'">'+fmtP(x.value)+'</b><br/>';});return s;}},legend:{top:0,textStyle:{color:muted,fontFamily:FONT,fontSize:11}},grid:{top:35,bottom:55,left:55,right:20},xAxis:{type:'category',data:dates,axisLabel:{color:muted,fontFamily:FONT,fontSize:10},axisLine:{lineStyle:{color:rule}}},yAxis:{type:'value',name:yn,nameTextStyle:{color:muted,fontFamily:FONT,fontSize:11},axisLabel:{color:muted,fontFamily:FONT,formatter:'{value}%'},splitLine:{lineStyle:{color:rule,type:'dashed'}},axisLine:{show:false}},dataZoom:[{type:'inside',start:0,end:100},{type:'slider',start:0,end:100,height:18,bottom:8,textStyle:{color:muted,fontFamily:FONT}}],series:s,animation:false};
  }

  function barOpt(field,yn){
    var pl=PRODUCTS.map(function(p){return D.products[p]?(p+'\n'+D.products[p].name):p;});
    var s=LABELS.map(function(l,i){return{name:l,type:'bar',data:PRODUCTS.map(function(p){return D.products[p]?D.products[p].current.contracts[l][field]:null;}),itemStyle:{color:CC[i]},barGap:'10%',barCategoryGap:'40%'};});
    if(s.length>0)s[0].markLine={silent:true,symbol:'none',lineStyle:{color:muted,type:'dashed',width:1},data:[{yAxis:0,label:{formatter:'升贴水分界',color:muted,fontFamily:FONT,fontSize:10}}]};
    return{textStyle:{fontFamily:FONT,color:ink},tooltip:{trigger:'axis',appendToBody:true,axisPointer:{type:'shadow'},formatter:function(p){var s=p[0].name.replace('\n',' ')+'<br/>';p.forEach(function(x){if(x.value==null)return;var c=x.value>0?pos:(x.value<0?neg:muted);s+=x.marker+x.seriesName+': <b style="color:'+c+'">'+fmtP(x.value)+'</b><br/>';});return s;}},legend:{data:LABELS,top:0,textStyle:{color:muted,fontFamily:FONT}},grid:{top:40,bottom:30,left:55,right:20},xAxis:{type:'category',data:pl,axisLabel:{color:muted,fontFamily:FONT,fontSize:11},axisLine:{lineStyle:{color:rule}}},yAxis:{type:'value',name:yn,nameTextStyle:{color:muted,fontFamily:FONT,fontSize:11},axisLabel:{color:muted,fontFamily:FONT,formatter:'{value}%'},splitLine:{lineStyle:{color:rule,type:'dashed'}},axisLine:{show:false}},series:s,animation:false};
  }

  function renderAll(){
    if(!D)return;
    renderCards();renderTable();renderStats();renderInsights();updateMeta();
    var dates=D.products['IF']?D.products['IF'].history.dates:[];
    var c;
    c=getChart('chart-snapshot-bar');if(c)c.setOption(barOpt('basis_rate','基差率(%)'));
    c=getChart('chart-annual-bar');if(c)c.setOption(barOpt('annualized_rate','年化基差率(%)'));
    c=getChart('chart-history-front');if(c){var s=PRODUCTS.map(function(p){return{name:p+' '+D.products[p].name,data:D.products[p].history['当月_rate'],color:PC[p]};});c.setOption(lineOpt(dates,s,'当月基差率(%)',true));}
    c=getChart('chart-history-annual');if(c){var s=PRODUCTS.map(function(p){return{name:p+' '+D.products[p].name,data:D.products[p].history['当月_annual'],color:PC[p]};});c.setOption(lineOpt(dates,s,'当月年化基差率(%)',true));}
    PRODUCTS.forEach(function(p){
      var id1='chart-'+p.toLowerCase()+'-rate',id2='chart-'+p.toLowerCase()+'-annual';
      c=getChart(id1);if(c){var pd=D.products[p];var s=LABELS.map(function(l,i){return{name:l,data:pd.history[l+'_rate'],color:CC[i]};});c.setOption(lineOpt(pd.history.dates,s,'基差率(%)',true));}
      c=getChart(id2);if(c){var pd=D.products[p];var s=LABELS.map(function(l,i){return{name:l,data:pd.history[l+'_annual'],color:CC[i]};});c.setOption(lineOpt(pd.history.dates,s,'年化基差率(%)',true));}
    });
  }

  // ================================================================
  // 纯前端数据更新（通过 CORS 代理从东方财富获取）
  // ================================================================
  function setupUpdateButton() {
    var btn = document.getElementById('btn-update');
    if (!btn) return;
    btn.addEventListener('click', function() {
      btn.classList.add('loading');
      btn.disabled = true;
      setStatus('正在更新数据...', 'loading');
      toast('正在从数据源拉取最新数据，请稍候...', 'info');

      if (typeof BasisAPI === 'undefined') {
        btn.classList.remove('loading');
        btn.disabled = false;
        setStatus('更新模块加载失败', 'error');
        toast('更新模块未加载，请刷新页面重试', 'error');
        return;
      }

      BasisAPI.incrementalUpdate(D).then(function(newData) {
        btn.classList.remove('loading');
        btn.disabled = false;
        if (newData && newData.meta) {
          D = newData;
          renderAll();
          setStatus('数据截至 ' + newData.meta.data_end + ' · ' + newData.meta.trading_days + ' 个交易日', 'ok');
          toast('数据更新成功！截至 ' + newData.meta.data_end, 'success');
        } else {
          setStatus('数据已是最新', 'ok');
          toast('当前数据已是最新，无需更新', 'info');
        }
      }).catch(function(err) {
        btn.classList.remove('loading');
        btn.disabled = false;
        setStatus('更新失败: ' + err.message, 'error');
        toast('更新失败: ' + err.message + '（可能是CORS代理暂时不可用，请稍后重试）', 'error');
      });
    });
  }

  // ================================================================
  // 初始化
  // ================================================================
  function init() {
    // 使用静态缓存数据立即渲染
    if (D) {
      renderAll();
      if (D.meta) {
        setStatus('数据截至 ' + (D.meta.data_end || '?') + ' · ' + (D.meta.trading_days || '?') + ' 个交易日（纯前端模式）', 'ok');
      } else {
        setStatus('缓存数据已加载（纯前端模式）', 'ok');
      }
    } else {
      setStatus('数据加载失败', 'error');
    }
    // 设置更新按钮
    setupUpdateButton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
