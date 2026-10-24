import { PanelSection, staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaFish } from "react-icons/fa";

export default definePlugin(() => ({
  name: "Mudfish VPN",
  titleView: <div className={staticClasses.Title}>Mudfish VPN</div>,
  content: <PanelSection />,
  icon: <FaFish />,
}));
