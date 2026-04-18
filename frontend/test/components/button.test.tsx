import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("渲染按钮文本", () => {
    render(<Button>点击我</Button>);
    expect(
      screen.getByRole("button", { name: "点击我" }),
    ).toBeInTheDocument();
  });

  it("点击触发onClick回调", async () => {
    const user = userEvent.setup();
    let clicked = false;
    render(<Button onClick={() => (clicked = true)}>按钮</Button>);

    await user.click(screen.getByRole("button"));
    expect(clicked).toBe(true);
  });

  it("disabled状态下不触发点击", async () => {
    const user = userEvent.setup();
    let clicked = false;
    render(
      <Button disabled onClick={() => (clicked = true)}>
        禁用按钮
      </Button>,
    );

    await user.click(screen.getByRole("button"));
    expect(clicked).toBe(false);
  });

  it("支持variant变体", () => {
    render(<Button variant="destructive">删除</Button>);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });
});
