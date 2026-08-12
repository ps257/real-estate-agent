import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { vnd } from "../format";

/**
 * action.type === "map" — kết quả map_listings: {count, points: [{id, title,
 * lat, lng, price_vnd, property_type}]}.
 *
 * Dùng circleMarker chứ không Marker mặc định: icon mặc định của Leaflet trỏ
 * tới file ảnh theo đường dẫn tương đối, và bundler (Vite) làm hỏng đường dẫn
 * đó — marker sẽ mất hình. circleMarker vẽ bằng SVG, không cần asset nào.
 */
export default function MapView({ action }) {
  const boxRef = useRef(null);
  const mapRef = useRef(null);
  const points = (action.map?.points || []).filter((p) => p.lat && p.lng);

  useEffect(() => {
    if (!boxRef.current || !points.length || mapRef.current) return;

    const map = L.map(boxRef.current, { scrollWheelZoom: false });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 19,
    }).addTo(map);

    const latlngs = points.map((p) => [p.lat, p.lng]);
    for (const p of points) {
      L.circleMarker([p.lat, p.lng], {
        radius: 7,
        weight: 2,
        color: "#1a6ef5",
        fillColor: "#1a6ef5",
        fillOpacity: 0.55,
      })
        // bindPopup nhận HTML -> phải escape dữ liệu từ MCP.
        .bindPopup(`<b>${esc(p.title || p.id)}</b><br>${esc(vnd(p.price_vnd))}`)
        .addTo(map);
    }
    map.fitBounds(L.latLngBounds(latlngs), { padding: [28, 28], maxZoom: 16 });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [points]);

  if (!points.length) return <p className="muted">(không có toạ độ)</p>;

  return (
    <div>
      <div ref={boxRef} className="map" />
      <p className="muted">{action.map?.count ?? points.length} điểm</p>
    </div>
  );
}

/** Escape thủ công vì Leaflet popup nhận chuỗi HTML, không phải JSX. */
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}
