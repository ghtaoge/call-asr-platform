declare module "lucide-react" {
  import type { ComponentType, SVGProps } from "react";

  export type IconProps = SVGProps<SVGSVGElement> & {
    size?: number | string;
  };

  export const Radio: ComponentType<IconProps>;
  export const ShieldAlert: ComponentType<IconProps>;
  export const Upload: ComponentType<IconProps>;
}
