import { useState } from "react";
import {
  User,
  Bot,
  ChevronDown,
  ChevronRight,
  Database,
  Clock,
  Gauge,
  Zap,
} from "lucide-react";

export default function MessageBubble({ message }) {
  const [showMeta, setShowMeta] = useState(false);
  const isUser = message.role === "user";
  const isError = message._isError;

  return (
    <div
      className={`flex gap-3 animate-slide-up ${isUser ? "flex-row-reverse" : ""}`}
    >
      {/* Avatar */}
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? "bg-brand-100 text-brand-600"
            : isError
              ? "bg-red-100 text-red-600"
              : "bg-emerald-100 text-emerald-600"
        }`}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Content */}
      <div className={`max-w-[75%] space-y-2 ${isUser ? "items-end" : ""}`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "bg-brand-600 text-white rounded-tr-md"
              : isError
                ? "bg-red-50 text-red-800 border border-red-200 rounded-tl-md"
                : "bg-white border border-surface-200 text-surface-800 rounded-tl-md"
          }`}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>

        {/* SQL Query Block */}
        {message.sql_query && (
          <div className="rounded-lg bg-surface-900 p-3 text-xs">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-surface-400">
              Generated SQL
            </p>
            <pre className="overflow-x-auto font-mono text-emerald-400">
              {message.sql_query}
            </pre>
          </div>
        )}

        {/* Metadata Toggle (assistant only) */}
        {!isUser && !isError && (message.confidence_score != null || message.agent_trace?.length > 0) && (
          <button
            onClick={() => setShowMeta((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-surface-400 hover:text-surface-600 transition-colors"
          >
            {showMeta ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Details
          </button>
        )}

        {/* Expanded Metadata */}
        {showMeta && !isUser && (
          <div className="animate-fade-in space-y-2 rounded-lg bg-surface-50 border border-surface-100 p-3 text-xs text-surface-600">
            <div className="flex flex-wrap gap-3">
              {message.confidence_score != null && (
                <span className="flex items-center gap-1">
                  <Gauge className="h-3 w-3" />
                  Confidence: {(message.confidence_score * 100).toFixed(0)}%
                </span>
              )}
              {message.latency_ms != null && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {Math.round(message.latency_ms)}ms
                </span>
              )}
              {message.cached && (
                <span className="flex items-center gap-1 text-amber-600">
                  <Zap className="h-3 w-3" />
                  Cached
                </span>
              )}
            </div>

            {message.tables_referenced?.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap">
                <Database className="h-3 w-3 text-surface-400" />
                {message.tables_referenced.map((t) => (
                  <span
                    key={t}
                    className="rounded bg-surface-200 px-1.5 py-0.5 font-mono text-[10px]"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            {message.agent_trace?.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-surface-200">
                <p className="text-[10px] font-medium uppercase tracking-wider text-surface-400">
                  Agent Pipeline
                </p>
                {message.agent_trace.map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        t.status === "success"
                          ? "bg-emerald-500"
                          : t.status === "skipped"
                            ? "bg-surface-300"
                            : "bg-red-500"
                      }`}
                    />
                    <span className="font-mono">{t.agent_type}</span>
                    <span className="text-surface-400">
                      {t.status} · {Math.round(t.duration_ms)}ms
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}