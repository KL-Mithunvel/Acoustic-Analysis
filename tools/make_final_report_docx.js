// Builds docs/FINAL_REPORT.docx from docs/FINAL_REPORT.md (the markdown stays the source).
//
//   NODE_PATH=<folder containing node_modules/docx> node tools/make_final_report_docx.js
//
// Handles exactly the markdown this report uses: # / ## / ### headings, paragraphs with **bold**, *italic* and
// `code`, > quotes, - and 1. lists, pipe tables (cells may hold images), images, italic caption lines and the
// numbered equation lines "(n) ...". A4, 2 cm margins, Times New Roman 11 pt, page numbers in the footer.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, Footer, PageNumber,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, LevelFormat, VerticalAlign,
} = require('docx');

const DOCS = path.resolve(__dirname, '..', 'docs');
const SRC = path.join(DOCS, 'FINAL_REPORT.md');
const OUT = path.join(DOCS, 'FINAL_REPORT.docx');
const PAGE_W = 11906, MARGIN = 1134, CONTENT_DXA = PAGE_W - 2 * MARGIN;   // 9638 DXA = 642 px at 96 dpi
const CONTENT_PX = Math.floor(CONTENT_DXA / 15);
const FONT = 'Times New Roman';

// ---------------------------------------------------------------- image sizes (PNG / JPEG headers)
function imageInfo(file) {
  const b = fs.readFileSync(file);
  if (b[0] === 0x89 && b[1] === 0x50) return { type: 'png', w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
  if (b[0] === 0xff && b[1] === 0xd8) {
    let i = 2;
    while (i < b.length) {
      if (b[i] !== 0xff) { i++; continue; }
      const m = b[i + 1];
      if (m >= 0xc0 && m <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(m)) return { type: 'jpg', w: b.readUInt16BE(i + 7), h: b.readUInt16BE(i + 5), data: b };
      i += 2 + b.readUInt16BE(i + 2);
    }
  }
  throw new Error('unreadable image: ' + file);
}

function imageRun(rel, alt, maxW, maxH) {
  const file = path.join(DOCS, rel);
  if (!fs.existsSync(file)) throw new Error('missing image ' + rel);
  const im = imageInfo(file);
  let w = Math.min(im.w, maxW), h = Math.round(im.h * w / im.w);
  if (h > maxH) { h = maxH; w = Math.round(im.w * h / im.h); }
  return new ImageRun({ type: im.type, data: im.data, transformation: { width: w, height: h },
    altText: { title: alt || path.basename(rel), description: alt || path.basename(rel), name: path.basename(rel) } });
}

// ---------------------------------------------------------------- inline markdown
function runs(text, base = {}) {
  text = text.replace(/z\*/g, 'z∗').replace(/Δ\*/g, 'Δ∗');        // literal stars in the equations
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith('**')) out.push(new TextRun({ text: t.slice(2, -2), ...base, bold: true }));
    else if (t.startsWith('*')) out.push(new TextRun({ text: t.slice(1, -1), ...base, italics: true }));
    else out.push(new TextRun({ text: t.slice(1, -1), ...base, font: 'Consolas', size: (base.size || 22) - 2 }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const IMG_RE = /!\[([^\]]*)\]\(([^)]+)\)/g;
const plain = (t) => t.replace(IMG_RE, '').replace(/[*`]/g, '').trim();

// ---------------------------------------------------------------- tables
const thin = { style: BorderStyle.SINGLE, size: 4, color: 'A0A7B0' };
const borders = { top: thin, bottom: thin, left: thin, right: thin };

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map((c) => c.trim());
}

function buildTable(lines) {
  let rows = lines.map(splitRow);
  rows = rows.filter((r) => !r.every((c) => /^:?-{2,}:?$/.test(c)));        // separator row
  const hasImg = rows.some((r) => r.some((c) => /!\[/.test(c)));
  const headerEmpty = rows[0].every((c) => c === '');
  if (headerEmpty) rows = rows.slice(1);
  const headerHasImg = rows[0].some((c) => /!\[/.test(c));
  const ncol = rows[0].length;
  const fs_ = ncol >= 6 ? 16 : ncol >= 4 ? 17 : 19;
  let widths;
  if (hasImg) widths = Array(ncol).fill(Math.floor(CONTENT_DXA / ncol));
  else {
    const wt = Array.from({ length: ncol }, (_, c) => 6 + Math.min(60, Math.max(...rows.map((r) => plain(r[c] || '').length))));
    const sum = wt.reduce((a, b) => a + b, 0);
    widths = wt.map((w) => Math.max(900, Math.floor(CONTENT_DXA * w / sum)));
    const diff = CONTENT_DXA - widths.reduce((a, b) => a + b, 0);
    widths[widths.indexOf(Math.max(...widths))] += diff;
  }
  const trows = rows.map((r, ri) => {
    const isHead = ri === 0 && !headerEmpty && !headerHasImg;
    const cells = r.map((c, ci) => {
      const kids = [];
      const parts = c.split(/(!\[[^\]]*\]\([^)]+\))/).map((p) => p.trim()).filter(Boolean);
      for (const part of parts) {
        const im = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(part);
        if (im) {
          const maxW = Math.floor(widths[ci] / 15) - 12;
          kids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 40, after: 40 }, keepNext: true,
            children: [imageRun(im[2], im[1], maxW, 330)] }));
        } else {
          kids.push(new Paragraph({ spacing: { before: 20, after: 20 }, alignment: hasImg ? AlignmentType.CENTER : AlignmentType.LEFT,
            children: runs(part, { size: hasImg ? 17 : fs_, font: FONT, bold: isHead || undefined }) }));
        }
      }
      if (!kids.length) kids.push(new Paragraph({ children: [] }));
      return new TableCell({
        borders, width: { size: widths[ci], type: WidthType.DXA }, verticalAlign: VerticalAlign.TOP,
        margins: { top: 40, bottom: 40, left: 80, right: 80 },
        shading: isHead ? { fill: 'E6EAF0', type: ShadingType.CLEAR, color: 'auto' } : undefined,
        children: kids,
      });
    });
    return new TableRow({ cantSplit: true, tableHeader: isHead, children: cells });
  });
  return new Table({ width: { size: CONTENT_DXA, type: WidthType.DXA }, columnWidths: widths, rows: trows });
}

// ---------------------------------------------------------------- document body
const md = fs.readFileSync(SRC, 'utf8').split(/\r?\n/);
const body = [];
let inRefs = false, listInstance = 0;

const spacer = (after = 120) => new Paragraph({ spacing: { after }, children: [] });

for (let i = 0; i < md.length; i++) {
  const line = md[i];
  const t = line.trim();
  if (!t || /^---+$/.test(t)) continue;

  let m;
  if ((m = /^(#{1,3}) (.+)$/.exec(t))) {
    const level = m[1].length, text = m[2];
    inRefs = text.trim() === 'References';
    if (level === 1) body.push(new Paragraph({ heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER, spacing: { before: 0, after: 200 }, children: runs(text, { bold: true, size: 34, font: FONT }) }));
    else body.push(new Paragraph({
      heading: level === 2 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
      pageBreakBefore: level === 2 && (text.startsWith('References') || text.startsWith('Appendix')),
      children: [new TextRun({ text, font: FONT })] }));
    continue;
  }
  if (t.startsWith('>')) {
    const q = [];
    while (i < md.length && md[i].trim().startsWith('>')) q.push(md[i++].trim().replace(/^>\s?/, ''));
    i--;
    body.push(new Paragraph({ spacing: { before: 80, after: 160 }, indent: { left: 200, right: 200 },
      shading: { fill: 'F1F4F8', type: ShadingType.CLEAR, color: 'auto' },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: '6B7785', space: 8 } },
      children: runs(q.join(' '), { italics: true, size: 20, font: FONT }) }));
    continue;
  }
  if (t.startsWith('|')) {
    const tl = [];
    while (i < md.length && md[i].trim().startsWith('|')) tl.push(md[i++]);
    i--;
    body.push(buildTable(tl));
    body.push(spacer(80));
    continue;
  }
  if (/^(\d+)\. /.test(t) || /^- /.test(t)) {
    const numbered = /^\d+\. /.test(t);
    const inst = ++listInstance;
    while (i < md.length && (numbered ? /^\d+\. /.test(md[i].trim()) : /^- /.test(md[i].trim()))) {
      const txt = md[i].trim().replace(/^(\d+\.|-) /, '');
      body.push(new Paragraph({ numbering: { reference: numbered ? 'numlist' : 'bullets', level: 0, instance: inst },
        spacing: { after: 60 }, children: runs(txt, { size: 22, font: FONT }) }));
      i++;
    }
    i--;
    body.push(spacer(60));
    continue;
  }
  if (/^(\s*!\[[^\]]*\]\([^)]+\)\s*)+$/.test(t)) {
    const imgs = [...t.matchAll(IMG_RE)];
    const each = Math.floor(CONTENT_PX / imgs.length) - 8;
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 },
      children: imgs.map((im, k) => imageRun(im[2], im[1], each, imgs.length > 1 ? 330 : 520)).flatMap((r, k) => (k ? [new TextRun('  '), r] : [r])) }));
    continue;
  }
  if (/^\*(Figure|Figures|Table)\b/.test(t) && t.endsWith('*')) {
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 }, children: runs(t, { size: 18, font: FONT }) }));
    continue;
  }
  if (/^\(\d+\) /.test(t)) {
    body.push(new Paragraph({ indent: { left: 360 }, spacing: { before: 60, after: 100 }, children: runs(t, { size: 22, font: FONT }) }));
    continue;
  }
  if (inRefs && !t.startsWith('**')) {
    body.push(new Paragraph({ indent: { left: 540, hanging: 540 }, spacing: { after: 100 }, children: runs(t, { size: 20, font: FONT }) }));
    continue;
  }
  body.push(new Paragraph({ alignment: t.length > 220 ? AlignmentType.JUSTIFIED : AlignmentType.LEFT, spacing: { after: 120, line: 276 },
    children: runs(t, { size: 22, font: FONT }) }));
}

const doc = new Document({
  creator: 'Mithunvel K. L.', title: 'A Time-of-Flight-Triggered, Sprung-Solenoid Impact-Acoustic Station for Clay Tile Inspection',
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', run: { size: 34, bold: true, font: FONT }, paragraph: { spacing: { after: 200 }, alignment: AlignmentType.CENTER } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 28, bold: true, font: FONT }, paragraph: { spacing: { before: 300, after: 120 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 24, bold: true, font: FONT }, paragraph: { spacing: { before: 200, after: 100 }, keepNext: true, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: 'numlist', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['Page ', PageNumber.CURRENT, ' of ', PageNumber.TOTAL_PAGES], size: 18, font: FONT })] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log('wrote', OUT, (buf.length / 1048576).toFixed(2) + ' MB,', body.length, 'blocks');
});
