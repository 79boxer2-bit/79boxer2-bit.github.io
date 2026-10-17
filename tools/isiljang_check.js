// 이실장 '네이버 모니터링' 화면 정리 버튼 (즐겨찾기 버튼으로 사용)
// - 사장님이 직접 연 화면에 이미 보이는 표만 읽어서 색칠·요약합니다.
// - 자동 접속·자동 클릭·저장·외부 전송 없음.
(function () {
  var ME = '하늘공인중개사';
  var T = function (e) { return (e && e.innerText || '').replace(/\s+/g, ' ').trim(); };
  var old = document.getElementById('hn-box');
  if (old) old.remove();
  document.querySelectorAll('[data-hn]').forEach(function (e) {
    e.style.background = ''; e.style.outline = ''; e.removeAttribute('data-hn');
  });

  // 표 머리줄(중개업소명이 있는 줄)을 찾아 칸 위치를 정한다
  var trs = [].slice.call(document.querySelectorAll('tr')), col = null, start = -1;
  for (var i = 0; i < trs.length && !col; i++) {
    var hc = [].slice.call(trs[i].children).map(T);
    if (hc.indexOf('중개업소명') < 0) continue;
    col = {};
    hc.forEach(function (x, j) {
      if (x === '순위') col.r = j;
      else if (x.indexOf('가격') === 0) col.p = j;
      else if (x === '동') col.d = j;
      else if (x === '층') col.f = j;
      else if (x === '면적') col.a = j;
      else if (x === '중개업소명') col.n = j;
      else if (x === '거래유형') col.t = j;
      else if (x === '동일매물') col.g = j;
    });
    start = i + 1;
  }
  if (!col || col.r == null || col.p == null || col.n == null) {
    alert('이실장 네이버 모니터링 표를 찾지 못했어요.\n매물관리 > 네이버 모니터링 화면에서 눌러 주세요.');
    return;
  }

  var price = function (s) {
    var m = s.replace(/,/g, '').match(/(\d+)(?:\s*\/\s*(\d+))?/);
    return m ? [+m[1], +(m[2] || 0)] : null;
  };
  var groups = [], cur = null;
  trs.slice(start).forEach(function (tr) {
    var c = tr.children;
    if (c.length <= col.n) return;
    var x = {
      tr: tr, rank: T(c[col.r]), p: price(T(c[col.p])), d: col.d != null ? T(c[col.d]) : '',
      f: col.f != null ? T(c[col.f]) : '', a: col.a != null ? T(c[col.a]) : '',
      t: col.t != null ? T(c[col.t]) : '', n: T(c[col.n])
    };
    if (!x.n || !x.p) return;
    x.me = x.n.indexOf(ME) >= 0;
    if (/^\d+$/.test(x.rank)) {
      var g = col.g != null ? T(c[col.g]) : '';
      var want = (g.match(/(\d+)\s*곳/) || [])[1];
      cur = { head: x, m: [x], want: want ? +want : 1 };
      groups.push(cur);
    } else if (cur) {
      cur.m.push(x);
    }
    x.g = cur;
  });

  var cheaper = function (o, me) {
    if (/월세|단기/.test(me.t)) return o.p[0] <= me.p[0] && o.p[1] <= me.p[1] && (o.p[0] !== me.p[0] || o.p[1] !== me.p[1]);
    return o.p[0] < me.p[0];
  };
  var paint = function (x, color) { x.tr.setAttribute('data-hn', '1'); x.tr.style.background = color; };
  var won = function (p) { return p[0].toLocaleString() + (p[1] ? '/' + p[1] : ''); };
  var desc = function (x) { return x.d + '동 ' + x.f + ' ' + x.t; };
  var short = function (n) { return n.replace(/(공인중개사사무소|공인중개사|중개사무소)$/, ''); };

  var behind = [], cheap = [], folded = 0, first = null;
  var all = groups.reduce(function (a, g) { return a.concat(g.m); }, []);
  groups.forEach(function (g) {
    if (g.m.length < g.want) folded++;
    var mine = g.m.filter(function (x) { return x.me; });
    if (!mine.length) return;
    // 밀림: 대표(맨 윗줄)가 우리가 아닌데 묶음 안에 우리 광고가 있음
    if (!g.head.me) {
      paint(g.head, '#ffd6d6');
      mine.forEach(function (x) { x.tr.setAttribute('data-hn', '1'); x.tr.style.outline = '2px solid #e03131'; });
      behind.push(g.head.rank + '위 ' + desc(g.head) + ' ' + won(g.head.p) + ' · 대표 ' + short(g.head.n));
      first = first || g.head.tr;
    }
    // 더 쌈: 같은 묶음, 또는 묶이지 않은 같은 동·층(숫자)·면적·거래 광고 중 우리보다 싼 것
    var me = mine.reduce(function (a, b) { return (b.p[0] < a.p[0] || (b.p[0] === a.p[0] && b.p[1] < a.p[1])) ? b : a; });
    all.forEach(function (o) {
      if (o.me || !cheaper(o, me)) return;
      var same = o.g === g;
      var solo = !same && /^\d+\//.test(me.f) && o.f === me.f && o.d === me.d && o.a === me.a && o.t === me.t;
      if (!same && !solo) return;
      paint(o, '#fff3bf');
      cheap.push(desc(me) + ' · ' + short(o.n) + ' ' + won(o.p) + ' < 우리 ' + won(me.p) + (solo ? ' (따로)' : ''));
      first = first || o.tr;
    });
  });

  var box = document.createElement('div');
  box.id = 'hn-box';
  box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;max-width:380px;max-height:70vh;overflow:auto;' +
    'background:#fff;border:2px solid #333;border-radius:10px;padding:12px 14px;font:14px/1.5 sans-serif;color:#222;box-shadow:0 4px 16px rgba(0,0,0,.25)';
  var esc = function (s) { return s.replace(/[&<>]/g, function (ch) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]; }); };
  var list = function (arr, color) {
    return arr.map(function (s) { return '<div style="border-left:4px solid ' + color + ';padding-left:6px;margin:3px 0">' + esc(s) + '</div>'; }).join('');
  };
  box.innerHTML = '<b style="font-size:16px">밀림 ' + behind.length + '건 · 더 싼 광고 ' + cheap.length + '건</b>' +
    '<div style="color:#666;font-size:12px">이 화면 묶음 ' + groups.length + '개 검사 · 닫으려면 이 상자를 누르세요</div>' +
    (folded ? '<div style="color:#c92a2a;font-size:12px;margin-top:4px">접혀 있는 묶음 ' + folded + '개는 펼친 뒤 다시 눌러 주세요</div>' : '') +
    list(behind, '#e03131') + list(cheap, '#f08c00') +
    '<div style="color:#666;font-size:12px;margin-top:6px">※ 지금 보이는 쪽만 검사합니다. 다음 쪽도 확인하세요.</div>';
  box.onclick = function () { box.remove(); };
  document.body.appendChild(box);
  if (first) first.scrollIntoView({ block: 'center' });
})();
