import { useState, useRef, useEffect } from "react";
import { SendHorizontal } from "lucide-react";

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2">
      <textarea
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask about your database schema..."
        disabled={disabled}
        rows={1}
        className="input-field resize-none min-h-[44px] max-h-[120px] py-3"
        style={{ height: "44px" }}
        onInput={(e) => {
          e.target.style.height = "44px";
          e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
        }}
      />
      <button
        type="submit"
        disabled={!text.trim() || disabled}
        className="btn-primary h-[44px] w-[44px] shrink-0 !p-0"
      >
        <SendHorizontal className="h-4 w-4" />
      </button>
    </form>
  );
}