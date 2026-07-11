import { Radio, Upload } from "lucide-react";
import type { Speaker } from "../types";

interface ToolbarProps {
  status: string;
  speaker: Speaker;
  onSpeakerChange: (speaker: Speaker) => void;
  onUpload: (file: File) => void;
  onRealtime: () => void;
}

export function Toolbar({ status, speaker, onSpeakerChange, onUpload, onRealtime }: ToolbarProps) {
  return (
    <header className="toolbar">
      <div>
        <h1>通话语音智能分析</h1>
        <p>{status}</p>
      </div>
      <div className="actions">
        <select value={speaker} onChange={(event) => onSpeakerChange(event.target.value as Speaker)} aria-label="当前说话人">
          <option value="sales">销售</option>
          <option value="customer">客户</option>
          <option value="unknown">未知</option>
        </select>
        <label className="fileButton" title="上传录音">
          <Upload size={18} />
          上传
          <input
            type="file"
            accept="audio/*"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file);
            }}
          />
        </label>
        <button type="button" title="实时演示" onClick={onRealtime}>
          <Radio size={18} />
          实时
        </button>
      </div>
    </header>
  );
}
