import Plyr from "plyr";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Section, Segment } from "../api/types";
import { formatClock } from "../utils/format";
import { ChevronDownIcon } from "./icons";

interface Props {
  src: string;
  poster?: string | null;
  subtitlesUrl?: string | null;
  segments?: Segment[];
  sourceLanguage?: "ru" | "en";
  targetLanguage?: "ru" | "en" | null;
  voiceoverUrl?: string | null;
  voiceoverAligned?: boolean;
  sections: Section[];
  currentTime: number;
  seekRequest: { sec: number; nonce: number } | null;
  onTime: (seconds: number) => void;
  onDuration: (seconds: number) => void;
  onSeek: (seconds: number) => void;
}

export function VideoPlayer({
  src,
  poster,
  segments = [],
  sourceLanguage = "ru",
  targetLanguage = null,
  voiceoverUrl = null,
  voiceoverAligned = false,
  sections,
  currentTime,
  seekRequest,
  onTime,
  onDuration,
  onSeek,
}: Props) {
  const holderRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<Plyr | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const voiceRef = useRef(false);
  const narrationRateRef = useRef(1);
  const alignedRef = useRef(false);
  const audioContextRef = useRef<AudioContext | null>(null);
  const originalGainRef = useRef<GainNode | null>(null);
  const timeRef = useRef(onTime);
  const durationRef = useRef(onDuration);
  const [ready, setReady] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [paused, setPaused] = useState(true);
  const [subtitleMode, setSubtitleMode] = useState<"off" | "source" | "target" | "both">("source");
  const [voiceover, setVoiceover] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  // Plyr's own container goes fullscreen, so overlays must live inside it.
  const [overlayHost, setOverlayHost] = useState<HTMLElement | null>(null);

  // Callbacks are stored in refs: otherwise every parent render would recreate
  // the Plyr instance (and the player would reset on each timeupdate).
  timeRef.current = onTime;
  durationRef.current = onDuration;
  alignedRef.current = voiceoverAligned;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const player = new Plyr(video, {
      controls: [
        "play-large",
        "play",
        "progress",
        "current-time",
        "duration",
        "mute",
        "volume",
        "pip",
        "fullscreen",
      ],
      keyboard: { focused: true, global: false },
      tooltips: { controls: true, seek: true },
      ratio: "16:9",
    });
    playerRef.current = player;

    const syncNarration = (force = false) => {
      const audio = audioRef.current;
      if (!voiceRef.current || !audio) return;
      // Narration cut by transcript timecodes maps 1:1 onto video seconds.
      // Legacy tracks are a single continuous mp3 without the original pauses,
      // so they can only be stretched over the whole duration.
      const aligned = alignedRef.current;
      const target = aligned ? player.currentTime : player.currentTime * narrationRateRef.current;
      // Correcting continuously would seek the narration backwards and repeat
      // words; a sub-second drift is inaudible.
      const tolerance = aligned ? 0.45 : 2.5;
      if (force || Math.abs(audio.currentTime - target) > tolerance) audio.currentTime = target;
    };
    const handleTime = () => { timeRef.current(player.currentTime); syncNarration(false); };
    const handleSeek = () => { timeRef.current(player.currentTime); syncNarration(true); };
    const handlePlay = () => { setPaused(false); if (voiceRef.current) void audioRef.current?.play().catch(() => undefined); };
    const handlePause = () => { setPaused(true); audioRef.current?.pause(); };
    const handleWaiting = () => { audioRef.current?.pause(); };
    const handlePlaying = () => {
      if (!voiceRef.current) return;
      syncNarration(false);
      void audioRef.current?.play().catch(() => undefined);
    };
    const handleVolume = () => {
      if (audioRef.current) audioRef.current.volume = player.muted ? 0 : player.volume;
    };
    const handleLoaded = () => {
      durationRef.current(player.duration || 0);
      setReady(true);
      setOverlayHost(player.elements.container as HTMLElement);
    };

    player.on("timeupdate", handleTime);
    player.on("loadedmetadata", handleLoaded);
    player.on("seeked", handleSeek);
    player.on("play", handlePlay);
    player.on("playing", handlePlaying);
    player.on("waiting", handleWaiting);
    player.on("pause", handlePause);
    player.on("ended", handlePause);
    player.on("volumechange", handleVolume);

    return () => {
      player.off("timeupdate", handleTime);
      player.off("loadedmetadata", handleLoaded);
      player.off("seeked", handleSeek);
      player.off("play", handlePlay);
      player.off("playing", handlePlaying);
      player.off("waiting", handleWaiting);
      player.off("pause", handlePause);
      player.off("ended", handlePause);
      player.off("volumechange", handleVolume);
      player.destroy();
      playerRef.current = null;
      setOverlayHost(null);
      setReady(false);
    };
  }, [src]);

  useEffect(() => () => {
    void audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
    originalGainRef.current = null;
  }, []);

  useEffect(() => {
    const player = playerRef.current;
    if (!player || !seekRequest) return;
    player.currentTime = seekRequest.sec;
    void Promise.resolve(player.play()).catch(() => undefined);
  }, [seekRequest]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !voiceoverUrl) return;
    const configure = () => {
      if (voiceoverAligned) {
        narrationRateRef.current = 1;
      } else {
        const videoDuration = playerRef.current?.duration || 0;
        if (videoDuration > 0 && audio.duration > 0) {
          narrationRateRef.current = Math.max(0.5, Math.min(2, audio.duration / videoDuration));
        }
      }
      audio.playbackRate = Math.max(0.5, Math.min(2, narrationRateRef.current * playbackSpeed));
    };
    configure();
    audio.addEventListener("loadedmetadata", configure);
    return () => audio.removeEventListener("loadedmetadata", configure);
  }, [voiceoverUrl, voiceoverAligned, playbackSpeed]);

  // Chapter separators on Plyr's progress bar (YouTube-like ticks).
  useEffect(() => {
    if (!ready || !sections.length) return;
    const holder = holderRef.current;
    const progress = holder?.querySelector(".plyr__progress") as HTMLElement | null;
    const duration = playerRef.current?.duration || 0;
    if (!progress || !duration) return;

    const marks: HTMLElement[] = [];
    for (const section of sections.slice(1)) {
      if (section.start_sec <= 0 || section.start_sec >= duration) continue;
      const mark = document.createElement("span");
      mark.className = "plyr__chapter-mark";
      mark.style.left = `${(section.start_sec / duration) * 100}%`;
      mark.title = section.title;
      progress.appendChild(mark);
      marks.push(mark);
    }
    return () => marks.forEach((mark) => mark.remove());
  }, [ready, sections]);

  const activeChapter =
    sections.find(
      (section) => currentTime >= section.start_sec && currentTime < section.end_sec,
    ) ?? sections[0];
  const activeSegment = segments.find((segment) => currentTime >= segment.start_sec && currentTime < segment.end_sec);
  const sourceLabel = sourceLanguage === "ru" ? "RU" : "EN";
  const targetLabel = targetLanguage === "ru" ? "RU" : "EN";

  const toggleVoiceover = () => {
    const next = !voiceover;
    setVoiceover(next);
    voiceRef.current = next;
    const player = playerRef.current;
    const audio = audioRef.current;
    if (!player || !audio) return;
    if (!audioContextRef.current && videoRef.current) {
      const AudioContextClass = window.AudioContext ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioContextClass) {
        const context = new AudioContextClass();
        const source = context.createMediaElementSource(videoRef.current);
        const gain = context.createGain();
        source.connect(gain).connect(context.destination);
        audioContextRef.current = context;
        originalGainRef.current = gain;
      }
    }
    if (audioContextRef.current?.state === "suspended") void audioContextRef.current.resume();
    if (originalGainRef.current) originalGainRef.current.gain.value = next ? 0 : 1;
    audio.volume = player.muted ? 0 : player.volume;
    audio.currentTime = player.currentTime * narrationRateRef.current;
    if (next && !player.paused) void audio.play().catch(() => undefined);
    else audio.pause();
  };

  const changeSpeed = (speed: number) => {
    setPlaybackSpeed(speed);
    if (playerRef.current) playerRef.current.speed = speed;
    if (audioRef.current) audioRef.current.playbackRate = Math.max(0.5, Math.min(2, narrationRateRef.current * speed));
  };

  const overlay = (
    <>
      <div
        className={`player-timecode ${paused ? "is-paused" : ""}`}
        title={paused ? "Пауза" : "Идёт воспроизведение"}
      >
        {paused && <span className="player-timecode__dot" />}
        {formatClock(currentTime)}
      </div>

      <div className={`player-settings ${settingsOpen ? "is-open" : ""}`}>
        <button className="player-settings__toggle" type="button" onClick={() => setSettingsOpen((open) => !open)} aria-expanded={settingsOpen} title="Настройки плеера">
          <span>⚙</span> Настройки
        </button>
        {settingsOpen && <div className="player-settings__menu">
          <div className="player-settings__section">
            <span className="player-settings__label">Субтитры</span>
            <div className="player-settings__options">
              <button className={subtitleMode === "off" ? "is-active" : ""} onClick={() => setSubtitleMode("off")}>Выкл.</button>
              <button className={subtitleMode === "source" ? "is-active" : ""} onClick={() => setSubtitleMode("source")}>{sourceLabel}</button>
              {targetLanguage && <button className={subtitleMode === "target" ? "is-active" : ""} onClick={() => setSubtitleMode("target")}>{targetLabel}</button>}
              {targetLanguage && <button className={subtitleMode === "both" ? "is-active" : ""} onClick={() => setSubtitleMode("both")}>Два языка</button>}
            </div>
          </div>
          <label className="player-settings__row"><span>Скорость</span><select value={playbackSpeed} onChange={(event) => changeSpeed(Number(event.target.value))}>{[0.75, 1, 1.25, 1.5, 1.75, 2].map((speed) => <option key={speed} value={speed}>{speed}×</option>)}</select></label>
          {voiceoverUrl && <div className="player-settings__row"><span>Аудио</span><button className={voiceover ? "is-active" : ""} onClick={toggleVoiceover}>{voiceover ? `Озвучка ${targetLabel}` : "Оригинал"}</button></div>}
        </div>}
      </div>

      {activeSegment && subtitleMode !== "off" && <div className="bilingual-subtitles">
        {(subtitleMode === "source" || subtitleMode === "both") && <span>{activeSegment.text}</span>}
        {(subtitleMode === "target" || subtitleMode === "both") && activeSegment.translated_text && <span className="is-translation">{activeSegment.translated_text}</span>}
      </div>}

      {sections.length > 0 && (
        <div className={`player-chapters ${chaptersOpen ? "is-open" : ""}`}>
          {chaptersOpen && (
            <div className="player-chapters__menu" role="menu" aria-label="Главы лекции">
              <div className="player-chapters__head">Главы лекции</div>
              <div className="player-chapters__list">
                {sections.map((section) => (
                  <button
                    key={section.id}
                    className={`player-chapter ${
                      section.id === activeChapter?.id ? "is-active" : ""
                    }`}
                    onClick={() => {
                      onSeek(section.start_sec);
                      setChaptersOpen(false);
                    }}
                  >
                    <span className="player-chapter__time">{section.timestamp}</span>
                    <span className="player-chapter__title">{section.title}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            className="player-chapters__toggle"
            onClick={() => setChaptersOpen((open) => !open)}
            aria-expanded={chaptersOpen}
            title="Главы лекции"
          >
            <span className="player-chapters__time">{activeChapter?.timestamp ?? "0:00"}</span>
            <span className="player-chapters__title">{activeChapter?.title ?? "Главы"}</span>
            <ChevronDownIcon size={14} />
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className="player-card">
      <div className="player-card__holder" ref={holderRef}>
        <video ref={videoRef} playsInline controls poster={poster ?? undefined} preload="metadata">
          <source src={src} />
        </video>
        {voiceoverUrl && <audio ref={audioRef} src={voiceoverUrl} preload="metadata" />}
        {overlayHost ? createPortal(overlay, overlayHost) : overlay}
      </div>
    </div>
  );
}
