import { staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { FaFish } from "react-icons/fa";
import { Panel } from "./Panel";

export default definePlugin(() => ({
  name: "Mudfish VPN",
  titleView: <div className={staticClasses.Title}>Mudfish VPN</div>,
  content: <Panel />,
  icon: <FaFish />,
}));
