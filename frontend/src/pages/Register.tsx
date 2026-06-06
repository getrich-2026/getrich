import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useNavigate, Link } from "react-router-dom";
import { useState } from "react";
import { register as registerApi } from "../api/auth";
import { useAuth } from "../contexts/AuthContext";
import { ApiClientError } from "../api/client";

const registerSchema = z
  .object({
    email: z
      .string()
      .min(1, "Email is required")
      .email("Please enter a valid email address"),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(/[A-Z]/, "Password must contain at least one uppercase letter")
      .regex(/[a-z]/, "Password must contain at least one lowercase letter")
      .regex(/[0-9]/, "Password must contain at least one number"),
    confirmPassword: z.string().min(1, "Please confirm your password"),
    name: z.string().max(128).optional(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type RegisterFormValues = z.infer<typeof registerSchema>;

export default function Register() {
  const navigate = useNavigate();
  const auth = useAuth();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: "", password: "", confirmPassword: "", name: "" },
  });

  const onSubmit = async (data: RegisterFormValues) => {
    setServerError(null);
    try {
      const res = await registerApi({
        email: data.email,
        password: data.password,
        name: data.name,
      });
      auth.login(res.data.access_token, res.data.user, res.data.refresh_token);
      navigate("/");
    } catch (err) {
      if (err instanceof ApiClientError) {
        setServerError(err.detail);
      } else {
        setServerError("Network error — is the API server running?");
      }
    }
  };

  return (
    <div style={{ maxWidth: 400, margin: "48px auto" }}>
      <h1 className="section-title" style={{ textAlign: "center" }}>
        Create Account
      </h1>
      <p
        className="text-muted"
        style={{ textAlign: "center", marginBottom: 24 }}
      >
        Sign up to start tracking your strategies.
      </p>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="card"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        {/* Server error banner */}
        {serverError && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: "var(--radius)",
              background: "var(--danger)",
              color: "var(--danger-foreground, #fff)",
              fontSize: 13,
            }}
          >
            {serverError}
          </div>
        )}

        {/* Name */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="name" style={{ fontWeight: 500, fontSize: 13 }}>
            Name <span className="text-muted">(optional)</span>
          </label>
          <input
            id="name"
            type="text"
            autoComplete="name"
            {...register("name")}
            style={{
              padding: "8px 12px",
              border: `1px solid ${errors.name ? "var(--danger)" : "var(--border)"}`,
              borderRadius: "var(--radius)",
              fontSize: 14,
              background: "var(--background)",
              color: "var(--foreground)",
            }}
          />
          {errors.name && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {errors.name.message}
            </span>
          )}
        </div>

        {/* Email */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="email" style={{ fontWeight: 500, fontSize: 13 }}>
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            {...register("email")}
            style={{
              padding: "8px 12px",
              border: `1px solid ${errors.email ? "var(--danger)" : "var(--border)"}`,
              borderRadius: "var(--radius)",
              fontSize: 14,
              background: "var(--background)",
              color: "var(--foreground)",
            }}
          />
          {errors.email && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {errors.email.message}
            </span>
          )}
        </div>

        {/* Password */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label htmlFor="password" style={{ fontWeight: 500, fontSize: 13 }}>
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            {...register("password")}
            style={{
              padding: "8px 12px",
              border: `1px solid ${errors.password ? "var(--danger)" : "var(--border)"}`,
              borderRadius: "var(--radius)",
              fontSize: 14,
              background: "var(--background)",
              color: "var(--foreground)",
            }}
          />
          {errors.password && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {errors.password.message}
            </span>
          )}
        </div>

        {/* Confirm Password */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label
            htmlFor="confirmPassword"
            style={{ fontWeight: 500, fontSize: 13 }}
          >
            Confirm Password
          </label>
          <input
            id="confirmPassword"
            type="password"
            autoComplete="new-password"
            {...register("confirmPassword")}
            style={{
              padding: "8px 12px",
              border: `1px solid ${errors.confirmPassword ? "var(--danger)" : "var(--border)"}`,
              borderRadius: "var(--radius)",
              fontSize: 14,
              background: "var(--background)",
              color: "var(--foreground)",
            }}
          />
          {errors.confirmPassword && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {errors.confirmPassword.message}
            </span>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isSubmitting}
          style={{
            padding: "10px 16px",
            marginTop: 8,
            border: "none",
            borderRadius: "var(--radius)",
            background: "var(--primary)",
            color: "var(--primary-foreground)",
            fontSize: 14,
            fontWeight: 600,
            cursor: isSubmitting ? "not-allowed" : "pointer",
            opacity: isSubmitting ? 0.7 : 1,
          }}
        >
          {isSubmitting ? "Creating account…" : "Create Account"}
        </button>

        <p
          className="text-muted"
          style={{ fontSize: 13, textAlign: "center", marginTop: 4 }}
        >
          Already have an account?{" "}
          <Link
            to="/login"
            style={{ color: "var(--primary)", fontWeight: 500 }}
          >
            Sign in
          </Link>
        </p>
      </form>
    </div>
  );
}
