type DocRecord = {
  index: number;
  json_path?: string;
  pdf_path?: string;
  png_path?: string | null;
  pdf_engine?: string;
};

type DocGridProps = {
  runId: string;
  docs: DocRecord[];
  docType?: string;
};

export default function DocGrid({ runId, docs, docType }: DocGridProps) {
  if (!docs.length) {
    return <div className="empty">No documents yet. Run Synthesize to generate artifacts.</div>;
  }

  return (
    <div className="docs">
      {docs.map((doc) => {
        const pngSrc =
          doc.png_path ?? `/api/runs/${runId}/docs/${doc.index}/png`;
        const jsonHref =
          doc.json_path ?? `/api/runs/${runId}/docs/${doc.index}/json`;
        const pdfHref =
          doc.pdf_path ?? `/api/runs/${runId}/docs/${doc.index}/pdf`;

        return (
          <div key={doc.index} className="doc-card">
            <img
              className="thumb"
              src={pngSrc}
              alt={`Document ${doc.index}`}
              loading="lazy"
            />
            <div className="meta">
              <strong>doc_{doc.index}</strong>
              {docType ? <span className="badge">{docType}</span> : null}
            </div>
            <div className="links">
              <a href={jsonHref} target="_blank" rel="noreferrer">
                JSON
              </a>
              <a href={pdfHref} target="_blank" rel="noreferrer">
                PDF ↓
              </a>
            </div>
          </div>
        );
      })}
    </div>
  );
}
