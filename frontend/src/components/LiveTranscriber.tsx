import { useEffect, useRef, useState, useImperativeHandle, forwardRef, useCallback } from "react";

interface LiveTranscriberProps {
  asrSocket: WebSocket | null;
  interimText: string;
  onRestartAsr: () => void;
  onCloseAsr: () => void;
  onRecordingChange?: (isRecording: boolean) => void;
  showButton?: boolean;
}

export interface LiveTranscriberHandle {
  toggleRecording: () => void;
  isRecording: boolean;
}

const LiveTranscriber = forwardRef<LiveTranscriberHandle, LiveTranscriberProps>(({
  asrSocket,
  interimText,
  onRestartAsr,
  onCloseAsr,
  onRecordingChange,
  showButton = true,
}, ref) => {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState("Idle");
  const isRecordingRef = useRef(false);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const asrSocketRef = useRef<WebSocket | null>(null);
  const pendingStartRef = useRef(false);

  const drawWaveform = () => {
    const analyser = analyserRef.current;
    const canvas = canvasRef.current;
    if (!analyser || !canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bufferLength = analyser.fftSize;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      if (!isRecordingRef.current || !analyserRef.current) {
        animationFrameRef.current = null;
        return;
      }

      analyser.getByteTimeDomainData(dataArray);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.beginPath();

      const sliceWidth = canvas.width / bufferLength;
      let x = 0;
      for (let i = 0; i < bufferLength; i += 1) {
        const v = dataArray[i] / 128.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }

      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 2;
      ctx.stroke();

      animationFrameRef.current = requestAnimationFrame(draw);
    };

    animationFrameRef.current = requestAnimationFrame(draw);
  };

  const cleanupWaveform = () => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  };

  const stopRecording = useCallback(() => {
    isRecordingRef.current = false;
    setIsRecording(false);
    onRecordingChange?.(false);
    pendingStartRef.current = false;

    try {
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    } catch {}
    mediaStreamRef.current = null;

    try {
      workletRef.current?.disconnect();
    } catch {}
    if (workletRef.current) {
      workletRef.current.port.onmessage = null;
      workletRef.current = null;
    }

    try {
      audioContextRef.current?.close();
    } catch {}
    audioContextRef.current = null;
    analyserRef.current = null;

    cleanupWaveform();
    setStatus("Idle");
    onCloseAsr();
  }, [onCloseAsr, onRecordingChange]);

  const startRecording = useCallback(async () => {
    const socket = asrSocketRef.current;
    if (!socket) {
      setStatus("Waiting for ASR socket…");
      pendingStartRef.current = true;
      onRestartAsr();
      return;
    }

    if (socket.readyState !== WebSocket.OPEN) {
      setStatus("Connecting to ASR…");
      pendingStartRef.current = true;
      onRestartAsr();
      return;
    }

    pendingStartRef.current = false;

    try {
      setStatus("Requesting microphone…");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioCtx = new AudioContext({ sampleRate: 16000 });

      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      const meta = import.meta as unknown as { env?: { BASE_URL?: string } };
      const baseUrl = meta?.env?.BASE_URL ?? "/";
      await audioCtx.audioWorklet.addModule(
        new URL(`${baseUrl}worklet/pcm-processor.js`, window.location.origin).toString()
      );

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;

      const workletNode = new AudioWorkletNode(audioCtx, "pcm-processor");

      mediaStreamRef.current = stream;
      audioContextRef.current = audioCtx;
      analyserRef.current = analyser;
      workletRef.current = workletNode;

      source.connect(analyser);
      source.connect(workletNode);

      workletNode.port.onmessage = (event) => {
        const ws = asrSocketRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(event.data);
        }
      };

      socket.addEventListener("close", () => {
        setStatus("ASR socket closed");
        stopRecording();
      });

      isRecordingRef.current = true;
      setIsRecording(true);
      onRecordingChange?.(true);
      setStatus("🔊 Streaming audio…");
      drawWaveform();
    } catch (err) {
      console.error("Failed to start recording", err);
      setStatus("Microphone permission denied");
      stopRecording();
    }
  }, [onRestartAsr, onRecordingChange, stopRecording]);

  const toggleRecording = () => {
    if (isRecordingRef.current) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  useEffect(() => {
    asrSocketRef.current = asrSocket;
    if (!asrSocket) {
      return;
    }

    const handleOpen = () => {
      if (pendingStartRef.current) {
        pendingStartRef.current = false;
        startRecording();
      }
    };

    if (pendingStartRef.current) {
      if (asrSocket.readyState === WebSocket.OPEN) {
        handleOpen();
      } else {
        asrSocket.addEventListener("open", handleOpen, { once: true });
        return () => {
          asrSocket.removeEventListener("open", handleOpen);
        };
      }
    }

    return () => {
      asrSocket.removeEventListener("open", handleOpen);
    };
  }, [asrSocket, startRecording]);

  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, []);

  useImperativeHandle(ref, () => ({
    toggleRecording,
    isRecording,
  }), [isRecording]);

  return (
    <div className="space-y-2">
      {showButton && (
        <div className="flex items-center gap-3">
          <button
            onClick={toggleRecording}
            className={`flex items-center justify-center w-12 h-12 rounded-full transition-all ${
              isRecording ? "bg-red-500 animate-pulse" : "bg-gray-700 hover:bg-gray-600"
            }`}
            title={isRecording ? "Stop recording" : "Start recording"}
          >
            <div className={`w-4 h-4 rounded ${isRecording ? "bg-white" : "bg-gray-300"}`} />
          </button>
          <canvas ref={canvasRef} width={220} height={40} className="bg-gray-800 rounded-lg" />
          <div className="flex-1 px-3 py-2 bg-gray-800/60 rounded-lg border border-gray-700/50 min-h-[2.5rem] flex items-center">
            <span className="sr-only">{status}</span>
            <span className="text-sm text-gray-300">
              {interimText || (isRecording ? "Listening…" : "Click record button to start voice chat")}
            </span>
          </div>
        </div>
      )}

      {!showButton && (
        <div className="flex items-center gap-3">
          <canvas ref={canvasRef} width={220} height={40} className="bg-gray-800 rounded-lg" />
          <div className="flex-1 px-3 py-2 bg-gray-800/60 rounded-lg border border-gray-700/50 min-h-[2.5rem] flex items-center">
            <span className="sr-only">{status}</span>
            <span className="text-sm text-gray-300">
              {interimText || (isRecording ? "Listening…" : "Ready to listen")}
            </span>
          </div>
        </div>
      )}
    </div>
  );
});

LiveTranscriber.displayName = "LiveTranscriber";

export default LiveTranscriber;
