import Plyr from "plyr";
import { useEffect, useRef } from "react";

interface Props {
  src: string;
  poster?: string | null;
  subtitlesUrl?: string | null;
  seekRequest: { sec: number; nonce: number } | null;
  onTime: (seconds: number) => void;
  onDuration: (seconds: number) => void;
}

export function VideoPlayer({ src, poster, subtitlesUrl, seekRequest, onTime, onDuration }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<Plyr | null>(null);

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
    const handleTime = () => onTime(player.currentTime);
    const handleLoaded = () => {
      onDuration(player.duration);
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
    };
  }, [src, onTime, onDuration]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player || !seekRequest) return;
    player.currentTime = seekRequest.sec;
    void Promise.resolve(player.play()).catch(() => undefined);
  }, [seekRequest]);

  return (
    <div className="player-card">
      <div className="player-card__holder">
        <video
          ref={videoRef}
          playsInline
          controls
          poster={poster ?? undefined}
          preload="metadata"
          crossOrigin="anonymous"
        >
          <source src={src} type="video/mp4" />
          {subtitlesUrl && (
            <track kind="captions" label="Русский" srcLang="ru" src={subtitlesUrl} default />
          )}
        </video>
      </div>
    </div>
  );
}
