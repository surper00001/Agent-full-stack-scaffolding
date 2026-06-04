/**
 * LoginForm 测试 — 覆盖表单验证、提交、错误展示。
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginForm } from "@/pages/login/login-form";

function renderLoginForm(props: {
  onSubmit?: () => Promise<void>;
  isSubmitting?: boolean;
  error?: string | null;
} = {}) {
  const onSubmit = props.onSubmit ?? vi.fn().mockResolvedValue(undefined);
  return {
    onSubmit,
    ...render(
      <MemoryRouter>
        <LoginForm
          onSubmit={onSubmit}
          isSubmitting={props.isSubmitting ?? false}
          error={props.error ?? null}
        />
      </MemoryRouter>,
    ),
  };
}

describe("LoginForm", () => {
  it("渲染账号、密码、验证码输入框和提交按钮", () => {
    renderLoginForm();

    expect(screen.getByPlaceholderText("用户名 / 邮箱 / 手机号")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("输入密码")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("图片中的 6 位数字")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /登录/ })).toBeInTheDocument();
  });

  it("空账号提交时显示验证错误", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderLoginForm();

    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("请输入账号")).toBeInTheDocument();
  });

  it("空密码提交时显示验证错误", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderLoginForm();

    await user.type(screen.getByPlaceholderText("用户名 / 邮箱 / 手机号"), "admin");
    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("请输入密码")).toBeInTheDocument();
  });

  it("验证码不足 6 位时显示错误", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderLoginForm();

    await user.type(screen.getByPlaceholderText("用户名 / 邮箱 / 手机号"), "admin");
    await user.type(screen.getByPlaceholderText("输入密码"), "password");
    await user.type(screen.getByPlaceholderText("图片中的 6 位数字"), "123");
    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("请输入 6 位验证码")).toBeInTheDocument();
  });

  it("有效表单提交触发 onSubmit", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderLoginForm();

    await user.type(screen.getByPlaceholderText("用户名 / 邮箱 / 手机号"), "admin");
    await user.type(screen.getByPlaceholderText("输入密码"), "password");
    await user.type(screen.getByPlaceholderText("图片中的 6 位数字"), "123456");
    await user.click(screen.getByRole("button", { name: /登录/ }));

    expect(onSubmit).toHaveBeenCalledWith("admin", "password", "123456");
  });

  it("isSubmitting 时按钮禁用", () => {
    renderLoginForm({ isSubmitting: true });

    const btn = screen.getByRole("button", { name: /验证中/ });
    expect(btn).toBeDisabled();
  });

  it("服务端错误展示", () => {
    renderLoginForm({ error: "账号或密码错误" });

    expect(screen.getByText("账号或密码错误")).toBeInTheDocument();
  });

  it("密码可见性切换", async () => {
    const user = userEvent.setup();
    renderLoginForm();

    const passwordInput = screen.getByPlaceholderText("输入密码");
    expect(passwordInput).toHaveAttribute("type", "password");

    // 点击眼睛图标
    const toggleBtn = screen.getByRole("button", { name: "" });
    // 找到密码切换按钮（眼睛图标）
    const buttons = screen.getAllByRole("button");
    const eyeButton = buttons.find((btn) =>
      btn.querySelector("svg") && !btn.textContent,
    );
    if (eyeButton) {
      await user.click(eyeButton);
      expect(passwordInput).toHaveAttribute("type", "text");
    }
  });

  it("包含注册导航链接", () => {
    renderLoginForm();

    expect(screen.getByText("立即注册")).toBeInTheDocument();
  });
});
