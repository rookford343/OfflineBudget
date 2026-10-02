export default function TripDetail({ tripId, onClose }: { tripId: number; onClose: () => void }) {
  return <div className="card">Trip {tripId} <button onClick={onClose}>Close</button></div>;
}
