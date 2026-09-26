import { useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";

const ACCEPTED_EXTENSIONS = [".tif", ".tiff"];

function isGeoTiff(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

interface GeoTiffDropzoneProps {
  file: File | null;
  disabled: boolean;
  onChange: (file: File | null) => void;
  onReject: (message: string) => void;
}

export function GeoTiffDropzone({ file, disabled, onChange, onReject }: GeoTiffDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function selectFile(candidate: File | undefined) {
    if (!candidate) return;
    if (!isGeoTiff(candidate)) {
      onReject("Only .tif or .tiff files are supported.");
      return;
    }
    onChange(candidate);
  }

  function openPicker() {
    if (!disabled) inputRef.current?.click();
  }

  function onInputChange(e: ChangeEvent<HTMLInputElement>) {
    selectFile(e.target.files?.[0]);
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
    selectFile(e.dataTransfer.files?.[0]);
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
        <strong>Drop a GeoTIFF here or click to browse</strong>
        <span className="muted upload-hint">Accepted formats: .tif, .tiff</span>
        <input ref={inputRef} type="file" accept={ACCEPTED_EXTENSIONS.join(",")} onChange={onInputChange} hidden />
      </div>

      {file && (
        <div className="upload-file">
          <span className="upload-file-icon">TIF</span>
          <div className="upload-file-meta">
            <strong title={file.name}>{file.name}</strong>
            <span className="muted">{formatSize(file.size)}</span>
          </div>
          {!disabled && (
            <button type="button" className="btn-ghost" onClick={() => onChange(null)}>
              Remove
            </button>
          )}
        </div>
      )}
    </>
  );
}
