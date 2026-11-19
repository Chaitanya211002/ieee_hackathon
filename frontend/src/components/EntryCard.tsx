import type { Entry } from "../types";
import AnalysisCard from "./cards/AnalysisCard";
import NoteCard from "./cards/NoteCard";
import PhotoCard from "./cards/PhotoCard";
import ProtocolCard from "./cards/ProtocolCard";
import VideoCard from "./cards/VideoCard";
import VoiceCard from "./cards/VoiceCard";

export default function EntryCard({ entry }: { entry: Entry }) {
  switch (entry.type) {
    case "voice":
      return <VoiceCard entry={entry} />;
    case "photo":
      return <PhotoCard entry={entry} />;
    case "video":
      return <VideoCard entry={entry} />;
    case "protocol_qa":
      return <ProtocolCard entry={entry} />;
    case "analysis":
      return <AnalysisCard entry={entry} />;
    default:
      return <NoteCard entry={entry} />;
  }
}
