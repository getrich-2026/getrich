interface TagProps {
  children: React.ReactNode
  variant?: 'red' | 'green' | 'blue' | 'orange' | 'gray' | 'ghost' | 'text'
  size?: 'default' | 'lg'
  className?: string
}

const variantStyles: Record<string, React.CSSProperties> = {
  red: {
    background: 'var(--gr-red-light)',
    color: 'var(--gr-red)',
    border: '1px solid var(--gr-red-border)',
  },
  green: {
    background: 'var(--gr-green-light)',
    color: 'var(--gr-green)',
    border: '1px solid #BBF7D0',
  },
  blue: {
    background: 'var(--gr-blue-light)',
    color: 'var(--gr-blue)',
    border: '1px solid #BFDBFE',
  },
  orange: {
    background: 'var(--gr-orange-light)',
    color: 'var(--gr-orange)',
    border: '1px solid #FDE68A',
  },
  gray: {
    background: '#F3F4F6',
    color: 'var(--gr-text-secondary)',
    border: '1px solid var(--gr-border)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--gr-text-secondary)',
    border: '1px solid var(--gr-border)',
  },
  text: {
    background: 'transparent',
    color: 'var(--gr-text)',
    border: 'none',
    padding: '0',
  },
}

export default function Tag({ children, variant = 'blue', size = 'default', className = '' }: TagProps) {
  const style = variantStyles[variant]
  const isText = variant === 'text'
  const padding = isText ? undefined : (size === 'lg' ? '4px 12px' : '2px 8px')
  const fontSize = size === 'lg' ? '13px' : '12px'
  const borderRadius = isText ? undefined : (size === 'lg' ? '6px' : '4px')

  return (
    <span
      className={`inline-flex items-center font-medium whitespace-nowrap ${className}`}
      style={{
        ...style,
        padding: padding ?? style.padding,
        fontSize,
        borderRadius: borderRadius ?? style.borderRadius,
        fontWeight: 500,
        lineHeight: 1.5,
      }}
    >
      {children}
    </span>
  )
}
