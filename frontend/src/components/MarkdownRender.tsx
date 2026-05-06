/**
 * Render markdown text with GitHub-flavored markdown extensions
 * (tables, strikethrough, task lists, autolinks).
 *
 * Used for:
 *   - F3 config_snapshot panel rendering long-text config fields.
 *   - A6 final-report rendering on the run-detail page.
 *
 * Image resolution: by default, image references in the markdown render
 * verbatim. For markdown that contains relative paths (e.g. AWF-1's
 * final report referencing chart artifacts by filename), the consumer
 * passes a `resolveImage` function that maps a relative path to an
 * authenticated URL — typically the run's artifact endpoint.
 *
 * Bootstrap-friendly defaults: tables get the standard `.table`
 * styling, code blocks get a muted background, headings preserve
 * their natural sizes.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  source: string;
  /**
   * Optional URL transformer for image references. Receives the raw
   * `src` from the markdown (e.g. `chart_001.png` or `./chart.png`)
   * and returns the URL to actually load. Return undefined to leave
   * the src as-is.
   */
  resolveImage?: (src: string) => string | undefined;
  className?: string;
}

const isAbsoluteUrl = (s: string): boolean =>
  /^[a-z][a-z0-9+.-]*:\/\//i.test(s) || s.startsWith("//") || s.startsWith("data:");

export default function MarkdownRender({ source, resolveImage, className }: Props) {
  return (
    <div className={`markdown-render ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: (props) => (
            <table className="table table-sm table-bordered" {...props} />
          ),
          code: ({ className: codeClass, children, ...rest }) => {
            // Inline code (no language class) gets a subtle inline style;
            // fenced blocks (with language class) get a muted block.
            const isBlock = codeClass && /^language-/.test(codeClass);
            if (isBlock) {
              return (
                <pre className="bg-light p-2 rounded small">
                  <code className={codeClass} {...rest}>
                    {children}
                  </code>
                </pre>
              );
            }
            return (
              <code className="bg-light px-1 rounded" {...rest}>
                {children}
              </code>
            );
          },
          img: ({ src, alt, ...rest }) => {
            if (typeof src !== "string" || !src) return null;
            const resolved =
              resolveImage && !isAbsoluteUrl(src) ? resolveImage(src) ?? src : src;
            return (
              <img
                src={resolved}
                alt={alt ?? ""}
                className="img-fluid my-2"
                {...rest}
              />
            );
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
