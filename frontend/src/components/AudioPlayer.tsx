import { useEffect, useRef } from 'react';
import { WS_BASE } from '../net';

interface AudioPlayerProps {
  sessionId: string;
  onAgentText: (text: string) => void;
  onResponseComplete: (text?: string) => void;
  onAudioStart: () => void;
  onAudioEnd: () => void;
}

const AudioPlayer: React.FC<AudioPlayerProps> = ({
  sessionId,
  onAgentText,
  onResponseComplete,
  onAudioStart,
  onAudioEnd,
}) => {
  const wsRef = useRef<WebSocket | null>(null);
  const audioQueueRef = useRef<Array<{ url: string; metadata?: any }>>([]);
  const isPlayingRef = useRef(false);
  const audioSessionStartedRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const responseBufferRef = useRef<string>('');
  const responseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastMetadataRef = useRef<any>(null);
  
  // Store callbacks in refs to prevent useEffect re-runs
  const onAgentTextRef = useRef(onAgentText);
  const onResponseCompleteRef = useRef(onResponseComplete);
  const onAudioStartRef = useRef(onAudioStart);
  const onAudioEndRef = useRef(onAudioEnd);

  // Update refs when callbacks change
  useEffect(() => {
    onAgentTextRef.current = onAgentText;
    onResponseCompleteRef.current = onResponseComplete;
    onAudioStartRef.current = onAudioStart;
    onAudioEndRef.current = onAudioEnd;
  }, [onAgentText, onResponseComplete, onAudioStart, onAudioEnd]);

  useEffect(() => {
    if (!sessionId) return;

    const playNextAudio = () => {
      // ABSOLUTE BLOCK: If already playing, DO NOT PROCEED
      if (isPlayingRef.current) {
        console.log('[AudioPlayer] BLOCKED: Already playing audio');
        return;
      }

      // Get next audio from queue
      const nextItem = audioQueueRef.current.shift();
      if (!nextItem) {
        console.log('[AudioPlayer] Queue empty, nothing to play');
        return;
      }

      const queueLength = audioQueueRef.current.length;
      
      console.log(`[AudioPlayer] PLAYING: "${nextItem.metadata?.sentence || 'unknown'}" (remaining: ${queueLength})`);

      const { url } = nextItem;

      // CREATE NEW AUDIO ELEMENT FOR EACH SENTENCE - no state pollution
      const audio = new Audio();

      // ATTACH TO DOM - critical for playback in some browsers
      if (containerRef.current) {
        containerRef.current.appendChild(audio);
      }

      // Set up handlers
      const handleEnded = () => {
        console.log(`[AudioPlayer] FINISHED: "${nextItem.metadata?.sentence || 'unknown'}"`);
        isPlayingRef.current = false;
        
        // Check if there are more items to play
        const hasMore = audioQueueRef.current.length > 0;
        
        // Only call onAudioEnd when this is the last sentence (no more in queue)
        if (!hasMore) {
          audioSessionStartedRef.current = false;
          onAudioEndRef.current();
        }

        // Clean up
        URL.revokeObjectURL(url);
        if (audio.parentNode) {
          audio.parentNode.removeChild(audio);
        }

        // Play next sentence AFTER this one is completely done
        setTimeout(() => playNextAudio(), 50); // Give time for cleanup
      };

      const handleError = (e: Event) => {
        // Ignore AbortError - it's just play() being interrupted, not a real error
        const error = e as ErrorEvent;
        if (error.error && error.error.name === 'AbortError') {
          console.log(`[AudioPlayer] Play interrupted (expected): "${nextItem.metadata?.sentence || 'unknown'}"`);
          return; // Don't treat as error, just return
        }
        
        console.error(`[AudioPlayer] ERROR playing: "${nextItem.metadata?.sentence || 'unknown'}"`, e);
        isPlayingRef.current = false;
        
        // Check if there are more items to play
        const hasMore = audioQueueRef.current.length > 0;
        
        // Only call onAudioEnd if no more items
        if (!hasMore) {
          audioSessionStartedRef.current = false;
          onAudioEndRef.current();
        }

        // Clean up
        URL.revokeObjectURL(url);
        if (audio.parentNode) {
          audio.parentNode.removeChild(audio);
        }

        // Try next
        setTimeout(() => playNextAudio(), 50);
      };

      const handlePlay = () => {
        console.log(`[AudioPlayer] STARTED: "${nextItem.metadata?.sentence || 'unknown'}"`);
      };

      audio.addEventListener('ended', handleEnded, { once: true });
      audio.addEventListener('error', handleError, { once: true });
      audio.addEventListener('play', handlePlay, { once: true });

      // Mark as playing and start
      isPlayingRef.current = true;
      
      // Only call onAudioStart for the first sentence of the response
      if (!audioSessionStartedRef.current) {
        audioSessionStartedRef.current = true;
        onAudioStartRef.current();
      }
      
      currentAudioRef.current = audio;

      // Set src and play - this audio element is dedicated to this sentence only
      audio.src = url;
      const playPromise = audio.play();
      
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            // Playback started successfully
            console.log(`[AudioPlayer] Play promise resolved: "${nextItem.metadata?.sentence || 'unknown'}"`);
          })
          .catch((error) => {
            // Only log if it's not an AbortError (which is expected when paused)
            if (error.name !== 'AbortError') {
              console.error(`[AudioPlayer] FAILED to play: "${nextItem.metadata?.sentence || 'unknown'}"`, error);
              handleError(error as any);
            } else {
              console.log(`[AudioPlayer] Play aborted (expected): "${nextItem.metadata?.sentence || 'unknown'}"`);
            }
          });
      }
    };

    const url = `${WS_BASE}/audio-out/${sessionId}`;
    console.log(`[AudioPlayer] Connecting to: ${url}`);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[AudioPlayer] WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        if (event.data instanceof Blob) {
          const metadata = lastMetadataRef.current;
          const objUrl = URL.createObjectURL(event.data);

          console.log(`[AudioPlayer] RECEIVED AUDIO BLOB: "${metadata?.sentence || 'no metadata'}"`);

          audioQueueRef.current.push({ url: objUrl, metadata: metadata ? { ...metadata } : null });
          console.log(`[AudioPlayer] QUEUED AUDIO: queue length now ${audioQueueRef.current.length}`);

          // Update text
          if (metadata?.sentence) {
            responseBufferRef.current += (responseBufferRef.current ? ' ' : '') + metadata.sentence;
            onAgentTextRef.current(responseBufferRef.current);
            console.log(`[AudioPlayer] TEXT BUFFER: "${responseBufferRef.current}"`);
          }

          lastMetadataRef.current = null;

          // Clear timeout
          if (responseTimeoutRef.current) {
            clearTimeout(responseTimeoutRef.current);
          }

          // Set new timeout
          responseTimeoutRef.current = setTimeout(() => {
            if (responseBufferRef.current && !isPlayingRef.current && audioQueueRef.current.length === 0) {
              console.log(`[AudioPlayer] FINALIZING RESPONSE: "${responseBufferRef.current}"`);
              onResponseCompleteRef.current(responseBufferRef.current);
              responseBufferRef.current = '';
            }
          }, 3000);

          // Start playing if not already playing
          console.log(`[AudioPlayer] CHECKING IF SHOULD START: isPlaying=${isPlayingRef.current}, queueLength=${audioQueueRef.current.length}`);
          if (!isPlayingRef.current) {
            console.log('[AudioPlayer] STARTING PLAYBACK');
            playNextAudio();
          }
        } else if (typeof event.data === 'string') {
          const data = JSON.parse(event.data);
          if (data.type === 'metadata' && data.sentence) {
            console.log(`[AudioPlayer] RECEIVED METADATA: "${data.sentence}"`);
            lastMetadataRef.current = data;
          } else if (data.type === 'stop') {
            console.log('[AudioPlayer] RECEIVED STOP SIGNAL');

            // Finalize current response
            if (responseBufferRef.current.trim()) {
              console.log(`[AudioPlayer] FINALIZING RESPONSE ON STOP: "${responseBufferRef.current}"`);
              onResponseCompleteRef.current(responseBufferRef.current);
            }

            // Clear everything for next response
            responseBufferRef.current = '';
            lastMetadataRef.current = null;

            if (responseTimeoutRef.current) {
              clearTimeout(responseTimeoutRef.current);
              responseTimeoutRef.current = null;
            }

            // Clear queue
            console.log(`[AudioPlayer] CLEARING QUEUE: ${audioQueueRef.current.length} items`);
            audioQueueRef.current.forEach(item => URL.revokeObjectURL(item.url));
            audioQueueRef.current = [];

            // Stop current playback - only if actually playing
            if (currentAudioRef.current && isPlayingRef.current) {
              console.log('[AudioPlayer] STOPPING CURRENT PLAYBACK');
              // Only pause if not already paused
              if (!currentAudioRef.current.paused) {
                try {
                  currentAudioRef.current.pause();
                } catch (e) {
                  // Ignore pause errors
                }
              }
              if (currentAudioRef.current.parentNode) {
                currentAudioRef.current.parentNode.removeChild(currentAudioRef.current);
              }
              currentAudioRef.current = null;
              isPlayingRef.current = false;
              audioSessionStartedRef.current = false;
              onAudioEndRef.current();
            }
          }
        }
      } catch (err) {
        console.warn('[AudioPlayer] Error:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[AudioPlayer] WebSocket error:', error);
    };

    ws.onclose = (event) => {
      console.log(`[AudioPlayer] WebSocket closed: code=${event.code}, reason=${event.reason || 'none'}`);
      wsRef.current = null;
    };

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (responseTimeoutRef.current) {
        clearTimeout(responseTimeoutRef.current);
      }
      // Stop current audio if playing - only pause if not already paused
      if (currentAudioRef.current) {
        if (!currentAudioRef.current.paused) {
          try {
            currentAudioRef.current.pause();
          } catch (e) {
            // Ignore pause errors during cleanup
          }
        }
        if (currentAudioRef.current.parentNode) {
          currentAudioRef.current.parentNode.removeChild(currentAudioRef.current);
        }
        currentAudioRef.current = null;
      }
      // Clean up queue
      audioQueueRef.current.forEach(item => URL.revokeObjectURL(item.url));
      audioQueueRef.current = [];
      isPlayingRef.current = false;
      audioSessionStartedRef.current = false;
    };
  }, [sessionId, WS_BASE]);

  return (
    <div ref={containerRef} style={{ display: 'none' }}>
      {/* Hidden container for dynamically created audio elements */}
    </div>
  );
};

export default AudioPlayer;
