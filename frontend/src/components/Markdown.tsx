import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** react-markdown never renders raw HTML, so AI/user text can't inject markup. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-trip">
      <ReactMarkdown remarkPlugins={[remarkGfm]}
        components={{ a: ({ href, children: c }) => <a href={href} target="_blank" rel="noopener noreferrer nofollow">{c}</a> }}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
