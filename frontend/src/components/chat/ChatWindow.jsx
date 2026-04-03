import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble";
import ChatInput from "./ChatInput";
import { MessageSquare } from "lucide-react";

export default function ChatWindow({ messages, sending, onSend }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 mb-4">
              <MessageSquare className="h-7 w-7 text-brand-500" />
            </div>
            <h3 className="text-lg font-semibold text-surface-800 mb-1">
              Ask about your database
            </h3>
            <p className="max-w-sm text-sm text-surface-400 leading-relaxed">
              Ask natural language questions about your SQL schema. The AI will
              find relevant tables, generate SQL, and execute it against your
              live database.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {[
                "What tables reference the Orders table?",
                "Show me the schema for customers",
                "How many indexes exist?",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => onSend(q)}
                  className="rounded-full border border-surface-200 bg-white px-3 py-1.5 text-xs text-surface-600 hover:border-brand-300 hover:text-brand-600 transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} />
            ))}

            {/* Typing indicator */}
            {sending && (
              <div className="flex items-center gap-3 animate-fade-in">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-100">
                  <div className="flex gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-dot" />
                    <span
                      className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-dot"
                      style={{ animationDelay: "0.2s" }}
                    />
                    <span
                      className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse-dot"
                      style={{ animationDelay: "0.4s" }}
                    />
                  </div>
                </div>
                <span className="text-xs text-surface-400">
                  Analyzing schema...
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-surface-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-3xl">
          <ChatInput onSend={onSend} disabled={sending} />
        </div>
      </div>
    </div>
  );
}