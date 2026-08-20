import Cards from "./Cards";
import { Cta, Clarify } from "./Chips";
import DynamicForm from "./DynamicForm";
import MapView from "./MapView";
import Overview from "./Overview";
import Compare from "./Compare";
import Sources from "./Sources";

/**
 * Bảng tra action.type -> component.
 *
 * Dùng bảng thay vì if/else để thêm loại mới chỉ là thêm một dòng, và quan
 * trọng hơn: loại CHƯA BIẾT rơi vào fallback thay vì làm vỡ cả câu trả lời.
 * Agent có thể thêm action mới (vd "detail") mà frontend chưa kịp cập nhật.
 */
const REGISTRY = {
  cards: Cards,
  cta: Cta,
  clarify: Clarify,
  form: DynamicForm,
  map: MapView,
  overview: Overview,
  compare: Compare,
  sources: Sources,
};

export default function ActionView({ action, onSend }) {
  const Component = REGISTRY[action.type];
  if (!Component) {
    return (
      <div className="note">
        Chưa hỗ trợ action <code>{action.type}</code>
        <pre>{JSON.stringify(action, null, 2)}</pre>
      </div>
    );
  }
  return <Component action={action} onSend={onSend} />;
}
