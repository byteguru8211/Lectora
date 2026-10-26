import Plyr from "plyr";
import { useEffect, useRef, useState } from "react";
import type { Section } from "../api/types";
import { ChevronDownIcon } from "./icons";

interface Props {
  src: string;
  poster?: string | null;
  subtitlesUrl?: string | null;
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
  subtitlesUrl,
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
  const timeRef = useRef(onTime);
  const durationRef = useRef(onDuration);
  const [ready, setReady] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);

  // Callbacks are stored in refs: otherwise every parent render would recreate
  // the Plyr instance (and the player would reset on each timeupdate).
  timeRef.current = onTime;
  durationRef.current = onDuration;

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
        "captions",
        "settings",
        "pip",
        "fullscreen",
      ],
      settings: ["captions", "speed"],
      speed: { selected: 1, options: [0.75, 1, 1.25, 1.5, 1.75, 2] },
      keyboard: { focused: true, global: false },
      tooltips: { controls: true, seek: true },
      captions: { active: true, update: true, language: "ru" },
      ratio: "16:9",
    });
    playerRef.current = player;

    const handleTime = () => timeRef.current(player.currentTime);
    const handleLoaded = () => {
      durationRef.current(player.duration || 0);
      setReady(true);
      try {
        const captions = (player as unknown as { captions?: { active: boolean } }).captions;
        if (captions) captions.active = true;
      } catch {
        /* captions may not be ready yet */
      }
    };

    player.on("timeupdate", handleTime);
    player.on("loadedmetadata", handleLoaded);
    player.on("seeked", handleTime);

    return () => {
      player.off("timeupdate", handleTime);
      player.off("loadedmetadata", handleLoaded);
      player.off("seeked", handleTime);
      player.destroy();
      playerRef.current = null;
      setReady(false);
    };
  }, [src]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player || !seekRequest) return;
    player.currentTime = seekRequest.sec;
    void Promise.resolve(player.play()).catch(() => undefined);
  }, [seekRequest]);

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

  return (
    <div className="player-card">
      <div className="player-card__holder" ref={holderRef}>
        <video ref={videoRef} playsInline controls poster={poster ?? undefined} preload="metadata">
          <source src={src} />
          {subtitlesUrl && (
            <track kind="captions" label="Русский" srcLang="ru" src={subtitlesUrl} default />
          )}
        </video>

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
      </div>
    </div>
  );
}
