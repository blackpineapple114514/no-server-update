/*!
 * update-check.js — 前端那一半：静默查一次、顶部小标签、「发现新版本」弹框。
 * 无依赖，原生 DOM，样式内联（不依赖宿主页面的 CSS 变量）。
 *
 *   installUpdateCheck({ endpoint: '/api/update/check', storageKey: 'app_seen_ver' })
 *
 * 约定（与后端 nou.Checker 对齐）：
 *   GET  <endpoint>[?force=1] -> {ok, current, latest, has_update, url, notes, error}
 *   POST <endpoint 同级的 /api/open_url> {url}  -> 让后端用系统浏览器打开下载页
 *
 * 三条行为规则：
 *   1. 自动检查失败**不打扰**（不弹窗、不 toast）；手动检查必须给反馈。
 *   2. 同一个版本只弹一次（localStorage 记版本号），标签一直保留。
 *   3. 只提示、不下载、不替换——真正的替换由用户完成。
 */
(function (global) {
  'use strict';

  var DEFAULTS = {
    endpoint: '/api/update/check',
    openUrlEndpoint: '/api/open_url',   // 传 '' 则直接用 location/open 打开
    storageKey: 'update_seen_ver',
    mount: '',                          // 选择器或元素：把标签挂进去；空则浮在右上角
    label: '检查更新',
    openText: '去下载',
    laterText: '稍后再说',
    autoDelay: 500,                     // 页面加载后多久静默检查（毫秒）
    title: '发现新版本'
  };

  function el(tag, css, text) {
    var e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text != null) e.textContent = text;
    return e;
  }

  function seen(key) {
    try { return localStorage.getItem(key) || ''; } catch (e) { return ''; }
  }
  function markSeen(key, ver) {
    try { localStorage.setItem(key, ver); } catch (e) { /* 隐私模式：只影响去重 */ }
  }

  function installUpdateCheck(opts) {
    var o = Object.assign({}, DEFAULTS, opts || {});
    var state = { last: null, busy: false };

    /* ---------- 小标签 ---------- */
    var pill = el('a', [
      'display:none', 'position:fixed', 'right:14px', 'top:14px', 'z-index:2147483000',
      'font:12px/1 system-ui,Segoe UI,Microsoft YaHei,sans-serif',
      'padding:7px 11px', 'border-radius:99px', 'cursor:pointer', 'text-decoration:none',
      'background:#1f6feb', 'color:#fff', 'box-shadow:0 4px 14px rgba(0,0,0,.25)'
    ].join(';'));
    pill.setAttribute('href', 'javascript:void(0)');

    var host = o.mount
      ? (typeof o.mount === 'string' ? document.querySelector(o.mount) : o.mount)
      : null;
    if (host) {
      pill.style.position = 'static';
      pill.style.boxShadow = 'none';
      host.appendChild(pill);
    } else {
      (document.body || document.documentElement).appendChild(pill);
    }

    /* ---------- 弹框 ---------- */
    function dialog(latest, url, current) {
      if (document.getElementById('uc-dlg')) return;
      var ov = el('div', 'position:fixed;inset:0;z-index:2147483001;background:rgba(6,10,18,.62);' +
        'display:flex;align-items:center;justify-content:center;padding:20px');
      ov.id = 'uc-dlg';
      var card = el('div', 'max-width:430px;width:100%;background:#161b26;color:#e6ecf5;' +
        'border:1px solid #2a3242;border-radius:14px;padding:22px 22px 16px;' +
        'box-shadow:0 18px 60px rgba(0,0,0,.5);font:14px/1.7 system-ui,Segoe UI,Microsoft YaHei,sans-serif');
      card.appendChild(el('div', 'font-size:16px;font-weight:600;margin-bottom:10px',
        o.title + ' v' + latest));
      card.appendChild(el('div', 'color:#9aa7bb',
        '当前版本 v' + current + '。点「' + o.openText + '」用浏览器打开下载页，' +
        '下载后手动替换即可——这个程序不会自己动文件。'));
      var row = el('div', 'display:flex;gap:10px;justify-content:flex-end;margin-top:18px');
      var later = el('button', 'padding:8px 16px;border-radius:9px;border:1px solid #2a3242;' +
        'background:transparent;color:#9aa7bb;cursor:pointer;font-size:13px', o.laterText);
      var go = el('button', 'padding:8px 18px;border-radius:9px;border:0;background:#3b82f6;' +
        'color:#fff;cursor:pointer;font-size:13px;font-weight:600', o.openText);
      row.appendChild(later);
      row.appendChild(go);
      card.appendChild(row);
      ov.appendChild(card);
      (document.body || document.documentElement).appendChild(ov);

      function close() { try { ov.remove(); } catch (e) { ov.parentNode.removeChild(ov); } }
      later.onclick = function () { markSeen(o.storageKey, latest); close(); };
      go.onclick = function () {
        markSeen(o.storageKey, latest);
        close();
        if (o.openUrlEndpoint) {
          fetch(o.openUrlEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
          }).catch(function () { /* 后端不通就退回直接开 */ global.open(url, '_blank', 'noopener'); });
        } else {
          global.open(url, '_blank', 'noopener');
        }
      };
      return ov;
    }

    /* ---------- 结果处理 ---------- */
    function apply(r, manual) {
      state.last = r;
      if (!r || !r.ok) {
        pill.style.display = 'none';
        if (manual) {
          var msg = (r && (r.error || (r.stale ? '检查失败（沿用上次结果）' : '检查失败'))) || '检查失败';
          if (global.console && console.warn) console.warn('[update] ' + msg);
          if (typeof o.onError === 'function') o.onError(msg, r);
          else global.alert('检查更新失败：' + msg + '\n\n可以手动打开下载页。');
        }
        return;
      }
      if (!r.has_update) {
        pill.style.display = 'none';
        if (manual && typeof o.onLatest === 'function') o.onLatest(r);
        return;
      }
      pill.textContent = '有新版本 v' + r.latest;
      pill.style.display = '';
      pill.onclick = function () { dialog(r.latest, r.url || '', r.current || ''); };
      if (manual || seen(o.storageKey) !== r.latest) {
        dialog(r.latest, r.url || '', r.current || '');
      }
    }

    function check(force) {
      if (state.busy) return Promise.resolve(state.last);
      state.busy = true;
      var url = o.endpoint + (force ? (o.endpoint.indexOf('?') < 0 ? '?' : '&') + 'force=1' : '');
      return fetch(url).then(function (x) { return x.json(); })
        .then(function (r) { apply(r, !!force); return r; })
        .catch(function (e) {
          apply({ ok: false, error: String(e).slice(0, 120) }, !!force);
          return null;
        })
        .then(function (r) { state.busy = false; return r; });
    }

    if (o.autoDelay >= 0) setTimeout(function () { check(false); }, o.autoDelay);
    return { check: check, apply: apply, dialog: dialog, pill: pill };
  }

  if (typeof module === 'object' && module.exports) module.exports = installUpdateCheck;
  else global.installUpdateCheck = installUpdateCheck;
})(typeof window !== 'undefined' ? window : this);
