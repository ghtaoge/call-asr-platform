import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { App } from "./App";

it("renders call asr workbench", () => {
  render(<App />);

  expect(screen.getByText("通话语音智能分析")).toBeInTheDocument();
  expect(screen.getByLabelText("通话内容")).toBeInTheDocument();
  expect(screen.getByLabelText("风险与质检")).toBeInTheDocument();
  expect(screen.getByLabelText("当前说话人")).toBeInTheDocument();
});
