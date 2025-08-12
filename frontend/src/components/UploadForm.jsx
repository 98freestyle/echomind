
import React, { useState, useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import { uploadFile, streamJob, downloadZip } from "../api";

export default function UploadForm() {
  const [file, setFile] = useState(null);
  const [stems, setStems] = useState(["vocals", "other"]);
  const [status, setStatus] = useState("");
  const [jobId, setJobId] = useState(null);
  const [done, setDone] = useState(false);
  const [showPreview, setShowPreview] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [evtSource, setEvtSource] = useState(null);
  const [error, setError] = useState("");
  const waveRefs = useRef({});
  const [playingStates, setPlayingStates] = useState({});
  const [volumes, setVolumes] = useState({});


  const toggleStem = (stem) => {
    setStems(prev =>
      prev.includes(stem) ? prev.filter(s => s !== stem) : [...prev, stem]
    );
  };

  const startUpload = async (selectedFile) => {
    if (!selectedFile) return;
    setFile(selectedFile);
    setUploading(true);
    setStatus("Uploading...");
    setDone(false);
    setShowPreview(true);
    setError("");

    let res;
    try {
      res = await uploadFile(selectedFile, stems);
      if (!res?.job_id) throw new Error("No job ID received.");
    } catch (err) {
      console.error(err);
      setError(err.message || "Upload failed. Please try again.");
      setUploading(false);
      return;
    }

    setJobId(res.job_id);
    setStatus("Processing...");

    const es = streamJob(res.job_id, (msg) => {
      setStatus(msg);
      if (msg.includes("Job complete")) {
        setTimeout(() => {
          setDone(true);
          setUploading(false);
        }, 500);
      }
    });

    setEvtSource(es);
  };


  const handleDownload = () => {
    if (jobId) {
      downloadZip(jobId, (errMsg) => setError(errMsg));
      setFile(null);
      setJobId(null);
      setDone(false);
      setStatus("");
      setShowPreview(false);
      setStems(["vocals", "other"]);
      setUploading(false);
      setPlayingStates({});
      setVolumes({});
    }
  };

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) startUpload(selectedFile);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) startUpload(droppedFile);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  useEffect(() => {
    return () => {
      if (evtSource) evtSource.close();
      Object.values(waveRefs.current).forEach(ws => ws.destroy());
    };
  }, [evtSource]);

  const createWaveform = (url, stem) => {
    const container = document.getElementById(`waveform-${stem}`);
    if (!container) return;

    if (waveRefs.current[stem]) {
      waveRefs.current[stem].destroy();
    }

    waveRefs.current[stem] = WaveSurfer.create({
      container: container,
      waveColor: "#4F46E5",
      progressColor: "#22C55E",
      cursorColor: "#FFFFFF",
      height: 80,
      barWidth: 2,
      responsive: true,
      volume: volumes[stem] ?? 1,
    });

    waveRefs.current[stem].load(url);
  };

  useEffect(() => {
    if (done && showPreview && jobId) {
      stems.forEach(stem => {
        const url = `http://127.0.0.1:5000/preview/${jobId}/${stem}`;
        createWaveform(url, stem);
      });
    }
  }, [done, showPreview, jobId]);

  const toggleStemPlay = (stem) => {
    const ws = waveRefs.current[stem];
    if (!ws) return;
    if (playingStates[stem]) {
      ws.pause();
      setPlayingStates(prev => ({ ...prev, [stem]: false }));
    } else {
      ws.play();
      setPlayingStates(prev => ({ ...prev, [stem]: true }));
    }
  };

  const handleVolumeChange = (stem, value) => {
    const vol = Math.max(0, Math.min(1, value));
    setVolumes(prev => ({ ...prev, [stem]: vol }));
    if (waveRefs.current[stem]) {
      waveRefs.current[stem].setVolume(vol);
    }
  };

  const startDrag = (stem, e) => {
    const bar = e.currentTarget;

    const updateVolume = (event) => {
      const rect = bar.getBoundingClientRect();
      const y = event.clientY - rect.top;
      const height = rect.height;
      const newVol = 1 - y / height;
      handleVolumeChange(stem, newVol);
    };

    updateVolume(e);

    const moveHandler = (event) => updateVolume(event);
    const upHandler = () => {
      window.removeEventListener("mousemove", moveHandler);
      window.removeEventListener("mouseup", upHandler);
    };

    window.addEventListener("mousemove", moveHandler);
    window.addEventListener("mouseup", upHandler);
  };

  return (
    <div
      className="bg-gray-800 bg-opacity-50 p-6 rounded-xl shadow-lg"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {error && (
        <div className="mb-4 p-3 bg-red-600 bg-opacity-80 rounded text-white text-sm">
          {error}
        </div>
      )}

      {!done && !uploading && (
        <>
          <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-gray-500 rounded-lg cursor-pointer hover:border-indigo-400 transition">
            <p className="text-gray-300 text-sm mb-2">
              Drag & Drop or Click to Select a File
            </p>
            <input
              type="file"
              onChange={handleFileSelect}
              className="hidden"
            />
          </label>

          <div className="flex flex-wrap gap-4 justify-center mt-4">
            {["vocals", "drums", "bass", "other"].map(stem => (
              <label key={stem} className="text-sm">
                <input
                  type="checkbox"
                  className="mr-2"
                  checked={stems.includes(stem)}
                  onChange={() => toggleStem(stem)}
                  disabled={uploading || jobId !== null}
                />
                {stem.charAt(0).toUpperCase() + stem.slice(1)}
              </label>
            ))}
          </div>
        </>
      )}

      {uploading && !done && (
        <div className="flex flex-col items-center justify-center mt-8">
          <div className="flex space-x-1 h-8">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="w-2 bg-indigo-500 rounded animate-pulse"
                style={{
                  animationDelay: `${i * 0.15}s`,
                  animationDuration: "1s",
                  height: "100%",
                  transformOrigin: "center bottom",
                  animationName: "wavePulse"
                }}
              />
            ))}
          </div>
          <p className="mt-4 text-gray-300 text-sm">{status}</p>

          <style>
            {`
              @keyframes wavePulse {
                0%, 100% { transform: scaleY(0.3); opacity: 0.5; }
                50% { transform: scaleY(1); opacity: 1; }
              }
              .animate-pulse {
                animation: wavePulse 1s ease-in-out infinite;
              }
            `}
          </style>
        </div>
      )}

      {done && (
        <div className="mt-6">
          <button
            onClick={handleDownload}
            className="bg-green-600 hover:bg-green-700 px-6 py-2 rounded-lg font-medium">
            Download Stems
          </button>

          {showPreview && (
            <div className="mt-6 bg-gray-900 p-4 rounded-lg">
              <h3 className="text-white mb-2">Preview Stems</h3>
              {stems.map(stem => (
                <div key={stem} className="mb-6 flex items-center space-x-3">
                  <button
                    onClick={() => toggleStemPlay(stem)}
                    className="bg-gray-700 hover:bg-gray-600 p-2 rounded-full flex items-center justify-center"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="w-6 h-6 text-white"
                      fill="currentColor"
                      viewBox="0 0 24 24"
                    >
                      {playingStates[stem] ? (
                        <path d="M6 4h4v16H6zm8 0h4v16h-4z" />
                      ) : (
                        <path d="M8 5v14l11-7z" />
                      )}
                    </svg>
                  </button>

                  <div id={`waveform-${stem}`} className="flex-1 bg-black rounded"></div>

                  <div
                    className="relative w-8 h-32 bg-gray-700 rounded-lg cursor-pointer flex flex-col justify-end items-center overflow-hidden"
                    onMouseDown={(e) => startDrag(stem, e)}
                  >
                    <div
                      className="absolute bottom-0 left-0 right-0 rounded-lg transition-all duration-200"
                      style={{
                        height: `${(volumes[stem] ?? 1) * 100}%`,
                        background: "linear-gradient(to top, #22C55E, #4F46E5)",
                      }}
                    ></div>
                    <span className="relative text-xs text-white font-bold mb-1 z-10">
                      {Math.round((volumes[stem] ?? 1) * 100)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
