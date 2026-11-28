import type {
  ReactNode,
  ButtonHTMLAttributes,
  HTMLAttributes,
  SVGProps,
} from "react";
export function Icon(
  props: SVGProps<SVGSVGElement> & { name?: string; size?: number },
): ReactNode;
export function Button(
  props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string },
): ReactNode;
export function Panel(
  props: Omit<HTMLAttributes<HTMLElement>, "title"> & {
    title?: ReactNode;
    action?: ReactNode;
  },
): ReactNode;
export function Badge(props: { children: ReactNode; tone?: string }): ReactNode;
export function Stat(props: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: string;
}): ReactNode;
export function Field(props: { label: string; children: ReactNode }): ReactNode;
export function Meter(props: {
  value: number | null;
  max?: number;
  tone?: string;
  label?: string;
}): ReactNode;
export function PageHeading(props: {
  eyebrow?: ReactNode;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}): ReactNode;
export function Tabs(props: {
  items: (string | { id: string; label: string })[];
  value: string;
  onChange: (id: string) => void;
}): ReactNode;
