import { useState, useEffect } from "react";
import { workflowApi, chatApi } from "../../api/client";
import { useChat } from "../../hooks/useChat";
import ChatWindow from "../../components/chat/ChatWindow";
import {
  GitBranch,
  MessageSquare,
  Plus,
  Loader2,
  History,
} from "lucide-react";

export default function ChatPage() {
  // Workflow selection
  const [workflows, setWorkflows] = useState([]);
  const [selectedWf, setSelectedWf] = useState(null);
  const [loadingWf, setLoadingWf] = useState(true);

  // Session sidebar
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(false);

  // Chat hook
  const {
    messages,
    sessionId,
    sending,
    error,
    sendMessage,
    loadSession,
    clearChat,
  } = useChat(selectedWf?.id);

  // Load workflows on mount
  useEffect(() => {
    workflowApi
      .listActive()
      .then(({ data }) => {
        setWorkflows(data.items);
        if (data.items.length > 0) {
          setSelectedWf(data.items[0]);
        }
      })
      .finally(() => setLoadingWf(false));
  }, []);

  // Load sessions when workflow changes
  useEffect(() => {
    if (!selectedWf) return;
    setLoadingSessions(true);
    chatApi
      .listSessions({ workflow_id: selectedWf.id })
      .then(({ data }) => setSessions(data.items))
      .finally(() => setLoadingSessions(false));
  }, [selectedWf?.id, sessionId]);

  const handleNewChat = () => {
    clearChat();
  };

  const handleLoadSession = async (sid) => {
    await loadSession(sid);
  };

  if (loadingWf) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-surface-400" />
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center px-4">
        <GitBranch className="h-10 w-10 text-surface-300 mb-3" />
        <h2 className="text-lg font-semibold text-surface-700">
          No workflows available
        </h2>
        <p className="text-sm text-surface-400 mt-1 max-w-sm">
          An admin needs to create a workflow first. Ask your admin to ingest a
          schema and create a workflow.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Session Sidebar */}
      <aside className="flex w-64 flex-col border-r border-surface-200 bg-white">
        {/* Workflow Selector */}
        <div className="border-b border-surface-100 p-3">
          <select
            value={selectedWf?.id || ""}
            onChange={(e) => {
              const wf = workflows.find((w) => w.id === e.target.value);
              setSelectedWf(wf);
              clearChat();
            }}
            className="input-field !py-2 text-sm"
          >
            {workflows.map((wf) => (
              <option key={wf.id} value={wf.id}>
                {wf.name}
              </option>
            ))}
          </select>
        </div>

        {/* New Chat Button */}
        <div className="p-3 pb-0">
          <button onClick={handleNewChat} className="btn-secondary w-full text-sm">
            <Plus className="h-3.5 w-3.5" /> New Chat
          </button>
        </div>

        {/* Session List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-surface-400">
            <History className="mr-1 inline h-3 w-3" />
            History
          </p>
          {loadingSessions ? (
            <div className="py-4 text-center">
              <Loader2 className="h-4 w-4 animate-spin mx-auto text-surface-300" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="px-2 py-3 text-xs text-surface-400 text-center">
              No conversations yet
            </p>
          ) : (
            sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => handleLoadSession(s.id)}
                className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                  sessionId === s.id
                    ? "bg-brand-50 border border-brand-200"
                    : "hover:bg-surface-50"
                }`}
              >
                <p className="truncate text-sm font-medium text-surface-700">
                  {s.title}
                </p>
                <p className="text-[11px] text-surface-400">
                  {s.message_count} messages ·{" "}
                  {new Date(s.updated_at).toLocaleDateString()}
                </p>
              </button>
            ))
          )}
        </div>
      </aside>

      {/* Chat Area */}
      <div className="flex-1">
        {selectedWf ? (
          <ChatWindow
            messages={messages}
            sending={sending}
            onSend={sendMessage}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-surface-400">
            Select a workflow to start chatting
          </div>
        )}
      </div>
    </div>
  );
}