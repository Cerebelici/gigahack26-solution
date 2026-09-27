import { useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";

const ACCEPTED_EXTENSIONS = [".tif", ".tiff", ".zip"];

function isAcceptedImagery(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function fileKind(file: File): "ZIP" | "TIF" {
  return file.name.toLowerCase().endsWith(".zip") ? "ZIP" : "TIF";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

interface GeoTiffDropzoneProps {
  files: File[];
  disabled: boolean;
  onChange: (files: File[]) => void;
  onReject: (message: string) => void;
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function GeoTiffDropzone({ files, disabled, onChange, onReject }: GeoTiffDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function selectFiles(candidates: FileList | File[] | undefined) {
    const incoming = candidates ? [...candidates] : [];
    if (incoming.length === 0) return;
    const rejected = incoming.filter((candidate) => !isAcceptedImagery(candidate));
    const accepted = incoming.filter((candidate) => isAcceptedImagery(candidate));
    if (accepted.length > 0) {
      const seen = new Set(files.map(fileKey));
      const next = [...files];
      for (const candidate of accepted) {
        const key = fileKey(candidate);
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(candidate);
      }
      onChange(next);
    }
    if (rejected.length > 0) {
      onReject("Only GeoTIFFs or zips of GeoTIFFs are supported.");
    }
  }

  function openPicker() {
    if (!disabled) inputRef.current?.click();
  }

  function onInputChange(e: ChangeEvent<HTMLInputElement>) {
    selectFiles(e.target.files ?? undefined);
    e.target.value = "";
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openPicker();
    }
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (!disabled) setDragging(true);
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    selectFiles(e.dataTransfer.files);
  }

  const dropzoneClass = ["dropzone", dragging && "dragging", disabled && "disabled"].filter(Boolean).join(" ");

  return (
    <>
      <div
        className={dropzoneClass}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={openPicker}
        onKeyDown={onKeyDown}
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <span className="dropzone-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <strong>Drop GeoTIFFs or zips of tiles here, or click to browse</strong>
        <span className="muted upload-hint">Several zips are stitched into one map. Accepted formats: .tif, .tiff, .zip</span>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          multiple
          onChange={onInputChange}
          hidden
        />
      </div>

      {files.length > 0 && (
        <ul className="upload-files">
          {files.map((file, index) => (
            <li key={fileKey(file)} className="upload-file">
              <span className="upload-file-icon">{fileKind(file)}</span>
              <div className="upload-file-meta">
                <strong title={file.name}>{file.name}</strong>
                <span className="muted">{formatSize(file.size)}</span>
              </div>
              {!disabled && (
                <button type="button" className="btn-ghost" onClick={() => onChange(files.filter((_, i) => i !== index))}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
