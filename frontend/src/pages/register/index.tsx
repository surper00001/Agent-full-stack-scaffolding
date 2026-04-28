import { LoginBrand } from "@/pages/login/login-brand";
import { RegisterForm } from "./register-form";

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen">
      {/* 左侧品牌区 — 复用登录页 */}
      <div className="hidden lg:flex lg:w-5/12 xl:w-1/2">
        <LoginBrand />
      </div>

      {/* 右侧注册表单 */}
      <div className="flex w-full lg:w-7/12 xl:w-1/2 items-center justify-center bg-background">
        <RegisterForm />
      </div>
    </div>
  );
}
