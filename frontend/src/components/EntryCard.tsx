import type { Entry } from "../types";
import AnalysisCard from "./cards/AnalysisCard";
import NoteCard from "./cards/NoteCard";
import PhotoCard from "./cards/PhotoCard";
import ProtocolCard from "./cards/ProtocolCard";
import VideoCard from "./cards/VideoCard";
import VoiceCard from "./cards/VoiceCard";

export default function EntryCard({ entry, onFollowUp }: { entry: Entry; onFollowUp?: (e: Entry) => void }) {
  switch (entry.type) {
    case "voice":
      return <VoiceCard entry={entry} />;
    case "photo":
      return <PhotoCard entry={entry} onFollowUp={onFollowUp} />;
    case "video":
      return <VideoCard entry={entry} onFollowUp={onFollowUp} />;
    case "protocol_qa":
      return <ProtocolCard entry={entry} />;
    case "analysis":
      return <AnalysisCard entry={entry} />;
    default:
      return <NoteCard entry={entry} />;
  }
}
