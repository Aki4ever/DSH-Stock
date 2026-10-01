/* ==========================================================================
 * DSH Stock Web —— 通用工具模块（web/modules/util.js）
 * 需求：REQ-053（v5.5.0 前端模块化拆分第一步）
 *
 * 约定：
 *   1. 本文件是**经典脚本**（非 ESM），必须在 web/app.js 之前用 <script> 加载；
 *      函数声明在全局作用域，与拆分前完全等价（调用点无需任何改动）。
 *   2. 这里只允许放**纯函数**：不得引用 DOM、不得读写 appState、不得有顶层副作用，
 *      以保证加载顺序与首屏时序完全不受影响。
 *   3. 迁出清单（逐一自 web/app.js 原样搬移，未改一字逻辑）：
 *      escapeActionText / escapeHtml / roundTo / formatStatVal / formatVolume /
 *      formatAmountYi / formatReal / estimateSvgTextWidth / layoutSubplotHeader / formatQuoteMoment
 * ========================================================================== */

function escapeActionText(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}


function escapeHtml(value) { return escapeActionText(String(value ?? "")); }


function roundTo(num, decimals) {
  const factor = Math.pow(10, decimals);
  return Math.round(num * factor) / factor;
}


function formatStatVal(v, unit) {
  if (v === undefined || v === null) return '--';
  if (unit === '亿元' && Math.abs(v) >= 10000) {
    return `${(v / 10000).toFixed(2)}万亿`;
  }
  return `${v}`;
}


function formatVolume(vol) {
  if (!vol || vol <= 0) return '0手';
  if (vol >= 10000) {
    return `${(vol / 10000).toFixed(2)}万`;
  }
  return `${Math.round(vol)}`;
}


function formatAmountYi(amtYi) {
  if (amtYi === null || amtYi === undefined) return '未提供';
  if (!amtYi || amtYi <= 0) return '0.00亿';
  if (amtYi < 0.01) {
    return `${(amtYi * 10000).toFixed(2)}万`;
  }
  return `${amtYi.toFixed(2)}亿`;
}


function formatReal(value,digits=2) { return value == null || !Number.isFinite(Number(value)) ? '未获取' : Number(value).toLocaleString(undefined,{maximumFractionDigits:digits}); }


function estimateSvgTextWidth(text, fontSize = 10) {
  const str = String(text == null ? '' : text);
  let units = 0;
  for (const ch of str) {
    const code = ch.codePointAt(0);
    if (code <= 0x2E7F) units += (ch === ' ') ? 0.34 : 0.6;
    else if ('（）：、，。％'.indexOf(ch) >= 0) units += 0.9;
    else units += 1.0;
  }
  return units * fontSize * 1.05;
}


function layoutSubplotHeader(options) {
  const opts = options || {};
  const x0 = Number(opts.x0) || 0;
  const y = Number(opts.y) || 0;
  const fontSize = Number(opts.fontSize) || 10;
  const maxRight = Number(opts.maxRight) || 0;
  const maxRows = Math.max(1, Number(opts.maxRows) || 3);
  const titleFill = opts.titleFill || '#94a3b8';
  const titleFontSize = Number(opts.titleFontSize) || fontSize;
  const baseGap = 12;
  const minGap = 6;
  const rowPitch = fontSize + 2;
  const title = String(opts.title || '');
  const items = Array.isArray(opts.items) ? opts.items : [];

  const titleWidth = title ? estimateSvgTextWidth(title, titleFontSize) : 0;
  const firstStart = x0 + (title ? titleWidth + baseGap : 0);
  const rows = [[]];
  let rowStart = firstStart;
  let cursor = firstStart;
  let dropped = 0;

  items.forEach(item => {
    const label = String(item.label == null ? '' : item.label);
    const value = (item.value === null || item.value === undefined) ? '' : ` ${item.value}`;
    const text = `${label}${value}`;
    const width = estimateSvgTextWidth(text, fontSize);
    let gap = (cursor === rowStart) ? 0 : baseGap;
    if (maxRight > 0 && cursor + gap + width > maxRight) {
      if (cursor + minGap + width <= maxRight) {
        gap = minGap;
      } else if (rows.length < maxRows) {
        rows.push([]);
        rowStart = x0;
        cursor = x0;
        gap = 0;
      } else {
        dropped++;   // 兜底：仍放不下时如实丢弃（不叠画），由返回的 dropped 让调用方可见
        return;
      }
    }
    rows[rows.length - 1].push({ label: label, value: value, fill: item.fill, x: cursor + gap, width: width, text: text });
    cursor = cursor + gap + width;
  });

  let svg = '';
  if (title) {
    svg += `<text x="${x0}" y="${y}" fill="${titleFill}" font-size="${titleFontSize}" font-weight="600">${title}</text>`;
  }
  rows.forEach((rowItems, rowIdx) => {
    if (!rowItems.length) return;
    const rowY = y + rowIdx * rowPitch;
    svg += '<g class="sub-summary-group">';
    rowItems.forEach(it => {
      svg += `<text x="${it.x.toFixed(2)}" y="${rowY}" fill="${it.fill || '#94a3b8'}" font-size="${fontSize}" font-family="monospace">`
        + `<tspan fill="#94a3b8">${it.label}</tspan>`
        + (it.value ? `<tspan font-weight="700" fill="${it.fill || '#f59e0b'}">${it.value}</tspan>` : '')
        + '</text>';
    });
    svg += '</g>';
  });
  return { svg: svg, rows: Math.max(1, rows.length), endX: cursor, dropped: dropped };
}


function formatQuoteMoment(value) {
  let date = null;
  let time = null;
  let raw = '';
  let precision = 'day';
  if (value && typeof value === 'object') {
    raw = String(value.raw || value.datetime || '');
    date = value.date ? String(value.date) : null;
    time = value.time ? String(value.time).slice(0, 5) : null;
    precision = value.precision || (time ? 'minute' : 'day');
  } else if (value) {
    raw = String(value);
    const digits = raw.replace(/\D/g, '');
    if (/^\d{8,}$/.test(raw.trim()) && digits.length >= 8) {
      date = `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
      time = digits.length >= 12 ? `${digits.slice(8, 10)}:${digits.slice(10, 12)}` : null;
    } else {
      const parts = raw.replace('T', ' ').trim().split(' ');
      date = parts[0] || null;
      time = parts[1] ? parts[1].slice(0, 5) : null;
    }
    precision = time ? 'minute' : 'day';
  }
  if (!date) return null;
  const mt = date.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (!mt) return null;
  const display = `${mt[1]}年${parseInt(mt[2], 10)}月${parseInt(mt[3], 10)}日${time ? ` ${time}` : ''}`;
  return { display: display, precision: precision, raw: raw || date, date: date, time: time };
}

