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
  const [activeAgentIndex, setActiveAgentIndex] = useState<number | null>(null);
  const [asrSocket, setAsrSocket] = useState<WebSocket | null>(null);
  const asrSocketRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pendingAgentRef = useRef<number | null>(null);
  const lastAgentTextRef = useRef("");
  const [selectedCharacter, setSelectedCharacter] = useState<string>("model_7");
  const [selectedScript, setSelectedScript] = useState<string>("script_1");

  // Create session and set character/script
  useEffect(() => {
    const createSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions`, { method: "POST" });
        if (!res.ok) throw new Error("Failed to create session");
        const data = await res.json();
        const newSessionId = data.session_id;
        setSessionId(newSessionId);
        
        // Enable RAG mode
        try {
          await fetch(`${API_BASE}/sessions/${newSessionId}/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              rag_mode: true,
              language: "ENG"
            }),
          });
        } catch (err) {
          console.warn("Failed to set RAG mode:", err);
        }
        
        // Set character
        try {
          const characterToSet = selectedCharacter || "model_7";
          await fetch(`${API_BASE}/set-character`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: characterToSet, session_id: newSessionId }),
          });
        } catch (err) {
          console.error("Failed to set character:", err);
        }
        
        // Set script
        try {
          await fetch(`${API_BASE}/set-script`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ script: selectedScript, session_id: newSessionId }),
          });
        } catch (err) {
          console.error("Failed to set script:", err);
        }
      } catch (err) {
        console.error("Session creation failed:", err);
      }
    };
    createSession();
  }, []);

  // Update character when selectedCharacter changes
  useEffect(() => {
    if (!sessionId || !selectedCharacter) return;
    
    const updateCharacter = async () => {
      try {
        await fetch(`${API_BASE}/set-character`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: selectedCharacter, session_id: sessionId }),
        });
      } catch (err) {
        console.error("Failed to update character:", err);
      }
    };
    
    updateCharacter();
  }, [selectedCharacter, sessionId]);

  // Update script when selectedScript changes
  useEffect(() => {
    if (!sessionId || !selectedScript) return;
    
    const updateScript = async () => {
      try {
        await fetch(`${API_BASE}/set-script`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ script: selectedScript, session_id: sessionId }),
        });
      } catch (err) {
        console.error("Failed to update script:", err);
      }
    };
    
    updateScript();
  }, [selectedScript, sessionId]);

  const handleAgentText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (pendingAgentRef.current === null && lastAgentTextRef.current === trimmed) {
      return;
    }
    setChatLog((prev) => {
      const updated = [...prev];
      if (pendingAgentRef.current === null) {
        pendingAgentRef.current = updated.length;
        setActiveAgentIndex(updated.length);
        return [...updated, { sender: "Agent", text: trimmed }];
      }
      updated[pendingAgentRef.current] = { sender: "Agent", text: trimmed };
      return updated;
    });
  }, []);

  const finalizeAgentResponse = useCallback((text?: string) => {
    setChatLog((prev) => {
      const updated = [...prev];
      if (pendingAgentRef.current === null) {
        const finalText = text?.trim();
        if (finalText) {
          if (lastAgentTextRef.current === finalText) {
            return updated;
          }
          lastAgentTextRef.current = finalText;
          return [...updated, { sender: "Agent", text: finalText }];
        }
        return updated;
      }
      if (text?.trim()) {
        updated[pendingAgentRef.current] = { sender: "Agent", text: text.trim() };
        lastAgentTextRef.current = text.trim();
      } else {
        lastAgentTextRef.current = updated[pendingAgentRef.current].text;
      }
      pendingAgentRef.current = null;
      setActiveAgentIndex(null);
      return updated;
    });
  }, []);

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
  }, [chatLog]);

  const setupAsrSocket = useCallback((socket: WebSocket) => {
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
  }, []);

  useEffect(() => {
    if (!sessionId) return;

    const socket = new WebSocket(`${WS_BASE}/audio-in/${sessionId}`);
    setupAsrSocket(socket);
    asrSocketRef.current = socket;
    setAsrSocket(socket);

    return () => {
      socket.close();
    };
  }, [sessionId, WS_BASE, setupAsrSocket]);

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
    setupAsrSocket(socket);
    asrSocketRef.current = socket;
    setAsrSocket(socket);
  }, [sessionId, WS_BASE, setupAsrSocket]);

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
                  {entry.sender === "Agent" && activeAgentIndex === index && (
                    <span className="ml-2 flex gap-1">
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse delay-150" />
                      <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse delay-300" />
                    </span>
                  )}
                </div>
                <div className="text-sm whitespace-pre-wrap break-words">{entry.text}</div>
              </div>
            </div>
          ))}

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
            <div className="flex-1 relative">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendText()}
                placeholder="Type your message or use the recording button below..."
                className="w-full px-4 py-3 pr-12 rounded-xl bg-gray-800 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={sendText}
                disabled={!input.trim()}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg bg-gradient-to-r from-blue-500 to-indigo-500 hover:from-blue-600 hover:to-indigo-600 disabled:opacity-50"
                title="Send"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M2.293 15.707a1 1 0 001.414 0l9-9V15a1 1 0 102 0V4a1 1 0 00-1-1H3a1 1 0 100 2h7.586l-9 9a1 1 0 000 1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
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
        onAudioStart={() => {}}
        onAudioEnd={() => {}}
      />
    </div>
  );
};

export default ChatRoom;
