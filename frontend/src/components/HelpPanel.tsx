import { X, HelpCircle } from "lucide-react";

interface Props {
  title: string;
  body: string;
  onClose: () => void;
}

export default function HelpPanel({ title, body, onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-start justify-end z-50 p-4" onClick={onClose}>
      <div
        className="card w-full max-w-sm mt-16 mr-2 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <HelpCircle size={18} className="text-indigo-500 shrink-0" />
            <h3 className="font-semibold text-gray-900 dark:text-gray-100 text-sm">{title}</h3>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 shrink-0">
            <X size={16} />
          </button>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed whitespace-pre-line">{body}</p>
      </div>
    </div>
  );
}
