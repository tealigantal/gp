import type { SVGProps } from 'react'

function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>
}

export const SparkIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4L12 3Z"/><path d="m19 14 .8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/></Icon>
export const PlusIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="M12 5v14M5 12h14"/></Icon>
export const ChatIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z"/><path d="M8 9h8M8 13h5"/></Icon>
export const TrashIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="M4 7h16M9 7V4h6v3"/><path d="m6.5 7 .8 13h9.4l.8-13M10 11v5M14 11v5"/></Icon>
export const ArrowIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="m5 12 7-7 7 7M12 19V5"/></Icon>
export const RefreshIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 9A7 7 0 0 1 18 6l2 2M18 15a7 7 0 0 1-11.9 3L4 16"/></Icon>
export const ShieldIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/></Icon>
export const TrendIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><path d="m3 17 6-6 4 4 8-9"/><path d="M15 6h6v6"/></Icon>
export const ClockIcon = (props: SVGProps<SVGSVGElement>) => <Icon {...props}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></Icon>
