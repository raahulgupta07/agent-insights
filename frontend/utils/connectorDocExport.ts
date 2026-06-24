// Generate a shareable Word (.docx) "Connection Setup Guide" from a ConnectorDoc.
// The `docx` lib is lazy-imported (mirrors the xlsx/pptxgenjs dynamic-import idiom
// in components/report/{Excel,Slides}Panel.vue) so it never bloats the main bundle.
import type { ConnectorDoc, FieldDoc } from './connectorDocs/types'

const CLAY = 'C2683F'
const INK = '1F2328'
const BODY = '6B6B6B'
const BORDER = 'E7E5DD'

function fieldList(doc: ConnectorDoc, fields: any[]): Array<{ name: string; title: string; fd: FieldDoc }> {
  const out: Array<{ name: string; title: string; fd: FieldDoc }> = []
  const seen = new Set<string>()
  const titleFor = (n: string) => {
    const f = (fields || []).find((x: any) => String(x?.field_name ?? x?.name) === n)
    return (f && (f.title || f.field_name)) || n
  }
  // Prefer the form's field order, then any extra documented fields.
  for (const f of fields || []) {
    const n = String(f?.field_name ?? f?.name ?? '').trim()
    if (!n || seen.has(n)) continue
    if (doc.fields[n]) {
      out.push({ name: n, title: f.title || n, fd: doc.fields[n] })
      seen.add(n)
    }
  }
  for (const [n, fd] of Object.entries(doc.fields)) {
    if (seen.has(n)) continue
    out.push({ name: n, title: titleFor(n), fd })
    seen.add(n)
  }
  return out
}

function whereSteps(fd: FieldDoc): string {
  const parts: string[] = []
  if (fd.where) parts.push(fd.where)
  if (fd.steps?.length) parts.push(fd.steps.map((s, i) => `${i + 1}. ${s}`).join('  '))
  if (fd.example) parts.push(`e.g. ${fd.example}`)
  if (fd.gotcha) parts.push(`⚠ ${fd.gotcha}`)
  return parts.join('\n') || '—'
}

export async function exportConnectorDocx(doc: ConnectorDoc, connectorLabel: string, fields: any[]) {
  const docx: any = await import('docx')
  const {
    Document, Packer, Paragraph, TextRun, HeadingLevel,
    Table, TableRow, TableCell, WidthType, BorderStyle, AlignmentType,
  } = docx

  const label = connectorLabel || 'Connector'
  const rows = fieldList(doc, fields)

  const heading = (text: string) =>
    new Paragraph({
      spacing: { before: 240, after: 120 },
      children: [new TextRun({ text, bold: true, color: CLAY, size: 26 })],
    })

  const body = (text: string, opts: any = {}) =>
    new Paragraph({
      spacing: { after: 120 },
      children: [new TextRun({ text, color: opts.color || BODY, size: opts.size || 21, bold: !!opts.bold })],
    })

  const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: BORDER }
  const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder }

  const headerCell = (text: string, width: number) =>
    new TableCell({
      width: { size: width, type: WidthType.PERCENTAGE },
      shading: { fill: 'F3E7DF' },
      borders: cellBorders,
      children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: '8A4427', size: 19 })] })],
    })

  const textCell = (text: string, width: number, opts: any = {}) =>
    new TableCell({
      width: { size: width, type: WidthType.PERCENTAGE },
      borders: cellBorders,
      children: text
        .split('\n')
        .map((line) => new Paragraph({ children: [new TextRun({ text: line, color: opts.color || INK, size: 19 })] })),
    })

  const tableRows = [
    new TableRow({
      tableHeader: true,
      children: [
        headerCell('Field', 16),
        headerCell('Required', 11),
        headerCell('What it is', 26),
        headerCell('Where to get it / steps', 32),
        headerCell('Your value', 15),
      ],
    }),
    ...rows.map(
      (r) =>
        new TableRow({
          children: [
            textCell(r.title, 16, { color: INK }),
            textCell(r.fd.required === false ? 'Optional' : 'Required', 11, {
              color: r.fd.required === false ? BODY : 'B4453A',
            }),
            textCell(r.fd.what || '—', 26, { color: BODY }),
            textCell(whereSteps(r.fd), 32, { color: BODY }),
            textCell('', 15),
          ],
        })
    ),
  ]

  const children: any[] = []

  // Branded title
  children.push(
    new Paragraph({
      heading: HeadingLevel.TITLE,
      spacing: { after: 80 },
      children: [new TextRun({ text: `${label} — Connection Setup Guide`, bold: true, color: CLAY, size: 40 })],
    })
  )
  children.push(body('Fill in these values to connect the data source. The last column is left blank for your team.', { color: BODY }))

  // Overview
  children.push(heading('Overview'))
  children.push(body(doc.overview || `Connection setup for ${label}.`))

  // Prerequisites
  if (doc.prerequisites?.length) {
    children.push(heading('Prerequisites'))
    for (const p of doc.prerequisites) {
      children.push(new Paragraph({ text: p, bullet: { level: 0 }, spacing: { after: 60 } }))
    }
  }

  // Fields table
  children.push(heading('Field requirements'))
  children.push(
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: tableRows,
    })
  )

  // Troubleshooting
  if (doc.troubleshooting?.length) {
    children.push(heading('Troubleshooting'))
    for (const t of doc.troubleshooting) {
      children.push(new Paragraph({ text: t, bullet: { level: 0 }, spacing: { after: 60 } }))
    }
  }

  // Docs link
  if (doc.docsUrl) {
    children.push(heading('Reference'))
    children.push(body(doc.docsUrl, { color: CLAY }))
  }

  // Footer
  children.push(
    new Paragraph({
      spacing: { before: 360 },
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: 'Generated by CityAgent Analytics', italics: true, color: '9A958C', size: 17 })],
    })
  )

  const file = new Document({
    styles: {
      default: { document: { run: { font: 'Calibri' } } },
    },
    sections: [{ properties: {}, children }],
  })

  const blob = await Packer.toBlob(file)
  const safe = label.replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '') || 'connector'
  triggerDownload(blob, `${safe}-setup-guide.docx`)
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
