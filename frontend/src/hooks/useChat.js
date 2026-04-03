import { useState, useCallback, useRef } from "react";
import { chatApi } from "../api/client";

export function useChat(workflowId) {
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() || sending) return;

      setError(null);
      setSending(true);

      // Optimistic: add user message immediately
      const userMsg = {
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      try {
        const { data } = await chatApi.send(workflowId, {
          message: text,
          session_id: sessionId,
        });

        setSessionId(data.session_id);

        // Add assistant response
        setMessages((prev) => [...prev, data.message]);

        return data;
      } catch (err) {
        const errMsg =
          err.response?.data?.error?.message || "Failed to send message";
        setError(errMsg);

        // Add error as a system message
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Error: ${errMsg}`,
            timestamp: new Date().toISOString(),
            _isError: true,
          },
        ]);
      } finally {
        setSending(false);
      }
    },
    [workflowId, sessionId, sending]
  );

  const loadSession = useCallback(async (sid) => {
    try {
      const { data } = await chatApi.getSession(sid);
      setSessionId(sid);
      setMessages(data.messages || []);
      return data;
    } catch (err) {
      setError("Failed to load session");
    }
  }, []);

  const clearChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setError(null);
  }, []);

  return {
    messages,
    sessionId,
    sending,
    error,
    sendMessage,
    loadSession,
    clearChat,
  };
}