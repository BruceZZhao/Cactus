import { useState, useEffect, useRef, useCallback } from "react";
import LiveTranscriber from "../components/LiveTranscriber";
import AudioPlayer from "../components/AudioPlayer";
import { API_BASE, WS_BASE } from "../net";

interface ChatMessage {
  sender: "You" | "Agent";
  text: string;
}

const ChatRoom: React.FC = () => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [chatLog, setChatLog] = useState<ChatMessage[]>([]);
  const [interimText, setInterimText] = useState("");
  const [currentAgentResponse, setCurrentAgentResponse] = useState("");
  const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
  const [asrSocket, setAsrSocket] = useState<WebSocket | null>(null);
  const asrSocketRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const createSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions`, { method: "POST" });
        if (!res.ok) throw new Error("Failed to create session");
        const data = await res.json();
        setSessionId(data.session_id);
      } catch (err) {
        console.error("Session creation failed:", err);
      }
    };
    createSession();
  }, []);

  const handleAgentText = useCallback((text: string) => {
    setCurrentAgentResponse(text);
  }, []);

  const finalizeAgentResponse = useCallback(
    (text?: string) => {
      const finalText = (text || currentAgentResponse).trim();
      if (!finalText) return;
      setChatLog((prev) => [...prev, { sender: "Agent", text: finalText }]);
      setCurrentAgentResponse("");
    },
    [currentAgentResponse]
  );

  const sendText = async () => {
    const message = input.trim();
    if (!message || !sessionId) return;

    setChatLog((prev) => [...prev, { sender: "You", text: message }]);
    setInput("");

    try {
      const res = await fetch(`${API_BASE}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: message, session_id: sessionId }),
      });
      if (!res.ok) {
        const errText = await res.text();
        console.error("Backend error:", errText);
        setChatLog((prev) => [...prev, { sender: "Agent", text: "[Error from server]" }]);
      }
    } catch (err) {
      console.error("Network error:", err);
      setChatLog((prev) => [...prev, { sender: "Agent", text: "[Failed to send message]" }]);
    }
  };

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatLog, currentAgentResponse]);

  useEffect(() => {
    if (!sessionId) return;

    const socket = new WebSocket(`${WS_BASE}/audio-in/${sessionId}`);
    asrSocketRef.current = socket;
    setAsrSocket(socket);

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "voice_interim" && typeof data.text === "string") {
          setInterimText(data.text);
        } else if (data.type === "voice_final" && typeof data.text === "string") {
          const text = data.text.trim();
          if (text) {
            setChatLog((prev) => [...prev, { sender: "You", text: `${text} (voice)` }]);
          }
          setInterimText("");
        }
      } catch (err) {
        console.warn("Failed to parse ASR message:", err);
      }
    };

    socket.onerror = (e) => console.error("ASR socket error", e);
    socket.onclose = () => {
      if (asrSocketRef.current === socket) {
        asrSocketRef.current = null;
        setAsrSocket(null);
      }
    };

    return () => {
      socket.close();
    };
  }, [sessionId, WS_BASE]);

  const restartAsrConnection = useCallback(() => {
    if (asrSocketRef.current) {
      try {
        asrSocketRef.current.close();
      } catch {}
      asrSocketRef.current = null;
      setAsrSocket(null);
    }
    if (!sessionId) return;
    const socket = new WebSocket(`${WS_BASE}/audio-in/${sessionId}`);
    asrSocketRef.current = socket;
    setAsrSocket(socket);
  }, [sessionId, WS_BASE]);

  const closeAsrConnection = useCallback(() => {
    if (asrSocketRef.current) {
      try {
        asrSocketRef.current.close();
      } catch {}
      asrSocketRef.current = null;
      setAsrSocket(null);
    }
  }, []);

  if (!sessionId) {
    return (
      <div className="h-screen w-screen bg-gray-900 text-white flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mx-auto" />
          <p>Creating session…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-gray-900 flex flex-col items-center py-6 px-4 text-white">
      <div className="w-full max-w-4xl bg-gray-850 rounded-2xl border border-gray-800 shadow-xl flex flex-col h-[90vh]">
        <header className="px-6 py-4 border-b border-gray-800">
          <h1 className="text-lg font-semibold">Project Cactus</h1>
          <p className="text-sm text-gray-400">Session: {sessionId.slice(0, 8)}</p>
        </header>

        <main className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {chatLog.map((entry, index) => (
            <div
              key={index}
              className={`flex ${entry.sender === "You" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[70%] px-4 py-3 rounded-2xl ${
                  entry.sender === "You"
                    ? "bg-gradient-to-br from-blue-600 to-indigo-600 text-white rounded-br-sm"
                    : "bg-gray-800 text-gray-100 rounded-bl-sm"
                }`}
              >
                <div className="text-xs uppercase tracking-wide mb-1 opacity-70">
                  {entry.sender}
                </div>
                <div className="text-sm whitespace-pre-wrap break-words">{entry.text}</div>
              </div>
            </div>
          ))}

          {currentAgentResponse && (
            <div className="flex justify-start">
              <div className="bg-gray-800 text-gray-100 px-4 py-3 rounded-2xl rounded-bl-sm max-w-[70%]">
                <div className="flex items-center gap-2 text-xs uppercase tracking-wide mb-1 opacity-70">
                  Agent
                  {isAgentSpeaking && (
                    <span className="flex gap-1">
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse delay-150" />
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse delay-300" />
                    </span>
                  )}
                </div>
                <div className="text-sm whitespace-pre-wrap break-words">{currentAgentResponse}</div>
              </div>
            </div>
          )}

          {interimText && (
            <div className="flex justify-end">
              <div className="bg-gray-800/60 text-gray-300 px-4 py-2 rounded-2xl rounded-br-sm max-w-[70%] text-sm italic border border-gray-700/50">
                {interimText}
              </div>
            </div>
          )}

          <div ref={scrollRef} />
        </main>

        <footer className="px-6 py-4 border-t border-gray-800 space-y-3 bg-gray-900/40">
          <div className="flex space-x-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendText()}
              placeholder="Type your message..."
              className="flex-1 px-4 py-3 rounded-xl bg-gray-800 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={sendText}
              disabled={!input.trim()}
              className="px-5 py-3 rounded-xl bg-gradient-to-r from-blue-500 to-indigo-500 hover:from-blue-600 hover:to-indigo-600 disabled:opacity-50"
            >
              Send
            </button>
          </div>

          <LiveTranscriber
            asrSocket={asrSocket}
            interimText={interimText}
            onRestartAsr={restartAsrConnection}
            onCloseAsr={closeAsrConnection}
          />
        </footer>
      </div>

      <AudioPlayer
        sessionId={sessionId}
        onAgentText={handleAgentText}
        onResponseComplete={finalizeAgentResponse}
        onAudioStart={() => setIsAgentSpeaking(true)}
        onAudioEnd={() => setIsAgentSpeaking(false)}
      />
    </div>
  );
};

export default ChatRoom;
