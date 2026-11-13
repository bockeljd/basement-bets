import React, { useEffect, useRef, useState } from 'react';
import { Info, Upload, X, CheckCircle2, AlertCircle } from 'lucide-react';
import api from '../../api/axios';

const ModelLogicDialog = ({ open, onClose, dataHealth = [], onKenpomUploaded }) => {
  const dialogRef = useRef(null);
  const fileInputRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadState, setUploadState] = useState({ uploading: false, status: 'idle', message: '' });

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open && typeof dialog.showModal === 'function') {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [open]);

  const handleBackdropClick = (event) => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const rect = dialog.getBoundingClientRect();
    const inside =
      rect.left <= event.clientX &&
      event.clientX <= rect.right &&
      rect.top <= event.clientY &&
      event.clientY <= rect.bottom;
    if (!inside) {
      onClose?.();
    }
  };

  const handleKenpomUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadState({ uploading: false, status: 'error', message: 'Please choose a KenPom CSV or TSV file first.' });
      return;
    }
    setUploadState({ uploading: true, status: 'uploading', message: '' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const res = await api.post('/api/admin/kenpom/upload-csv', formData);
      const rowsCount = res?.data?.rows ?? 'all';
      const asof = res?.data?.asof_date ? ` (as of ${res.data.asof_date})` : '';
      setUploadState({
        uploading: false,
        status: 'success',
        message: `Uploaded ${rowsCount} KenPom rows${asof}. Refreshing board predictions...`,
      });
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onKenpomUploaded?.();
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || 'Upload failed';
      setUploadState({ uploading: false, status: 'error', message: String(detail) });
    }
  };

  const bySource = {};
  (dataHealth || []).forEach((item) => {
    if (item?.source) bySource[item.source] = item;
  });

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="modelInfoDialogTitle"
      onCancel={(e) => {
        e.preventDefault();
        onClose?.();
      }}
      onClick={handleBackdropClick}
      className="today-modal w-[94dvw] bg-slate-900 text-slate-100 border border-slate-700/80 rounded-2xl shadow-2xl p-0 overflow-hidden m-auto"
    >
      <div className="flex flex-col min-h-0 max-h-[90dvh]">
        <div className="flex items-center justify-between px-5 py-4 bg-slate-950/90 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-blue-500/15 border border-blue-400/30 text-blue-400">
              <Info size={18} aria-hidden="true" />
            </div>
            <div>
              <h2 id="modelInfoDialogTitle" className="text-lg font-bold text-white">
                How the Model Works & Data Sources
              </h2>
              <p className="text-xs text-slate-400">
                Plain-English guide to our multi-source projections, player injury pricing, and KenPom CSV import
              </p>
            </div>
          </div>

          <form method="dialog">
            <button
              type="submit"
              onClick={onClose}
              aria-label="Close model logic guide"
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 cursor-pointer"
            >
              <X size={14} aria-hidden="true" />
              <span>Close</span>
            </button>
          </form>
        </div>

        <div className="p-5 overflow-y-auto space-y-5 text-xs leading-relaxed">
          <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2">
            <h3 className="font-bold uppercase tracking-wider text-indigo-300">
              1. Market-First Multi-Source Blending
            </h3>
            <p className="text-slate-300">
              We anchor on the live sportsbook consensus line and blend independent adjustments from{' '}
              <strong>BartTorvik</strong>, <strong>Haslametrics</strong>, and <strong>KenPom</strong>, layered with
              player-level injury impacts, Action Network ticket/money RLM splits, and referee whistle tendencies. A play
              is published only when edge reaches at least <strong>1.5 points</strong> and{' '}
              <strong>+2.0% EV</strong> after calibration.
            </p>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-3">
            <h3 className="font-bold uppercase tracking-wider text-emerald-300">
              2. Live Feed Health Status
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {['torvik', 'kenpom', 'haslametrics', 'odds', 'action_splits'].map((src) => {
                const row = bySource[src];
                const ok = String(row?.status || '').toLowerCase() === 'ok';
                return (
                  <div key={src} className="rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-2">
                    <div className="font-bold uppercase text-[10px] text-slate-400">{src}</div>
                    <div className={`mt-0.5 font-semibold ${ok ? 'text-emerald-300' : 'text-amber-300'}`}>
                      {row?.status || 'unknown'}
                      {row?.row_count != null ? ` (${row.row_count} rows)` : ''}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4 space-y-3">
            <h3 className="font-bold uppercase tracking-wider text-indigo-300">
              3. Upload KenPom Ratings (CSV / TSV)
            </h3>
            <p className="text-slate-300">
              Export your daily ratings CSV or TSV from KenPom and upload it here to refresh team ratings immediately.
            </p>
            <form onSubmit={handleKenpomUpload} className="flex flex-wrap items-center gap-3">
              <div>
                <label htmlFor="kenpom-csv-file" className="block text-[11px] font-semibold text-slate-300 mb-1">
                  KenPom CSV / TSV File
                </label>
                <input
                  id="kenpom-csv-file"
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.tsv,.txt"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-100 file:font-semibold hover:file:bg-slate-700"
                />
              </div>
              <button
                type="submit"
                disabled={uploadState.uploading || !selectedFile}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs cursor-pointer self-end"
              >
                <Upload size={13} aria-hidden="true" />
                <span>{uploadState.uploading ? 'Uploading...' : 'Import KenPom'}</span>
              </button>
            </form>

            {uploadState.message && (
              <div
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
                  uploadState.status === 'success'
                    ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-200'
                    : 'bg-rose-500/15 border border-rose-500/30 text-rose-200'
                }`}
              >
                {uploadState.status === 'success' ? (
                  <CheckCircle2 size={14} aria-hidden="true" />
                ) : (
                  <AlertCircle size={14} aria-hidden="true" />
                )}
                <span>{uploadState.message}</span>
              </div>
            )}
          </section>
        </div>
      </div>
    </dialog>
  );
};

export default ModelLogicDialog;
