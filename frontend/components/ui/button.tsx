import * as React from "react"
import { cn } from "@/lib/utils"

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { 
    variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive',
    size?: 'default' | 'sm' | 'lg' | 'icon'
  }
>(({ className, variant = 'primary', size = 'default', ...props }, ref) => {
  const variants = {
    primary: "bg-primary text-primary-foreground hover:bg-primary/90",
    secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
    outline: "border border-input bg-background hover:bg-muted hover:text-muted-foreground",
    // For secondary actions sitting inside a row that already has a primary
    // one, where a bordered button would compete with it for attention.
    ghost: "hover:bg-muted hover:text-foreground",
    destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
  }

  const sizes = {
    default: "h-10 px-4 py-2",
    sm: "h-9 rounded-md px-3",
    lg: "h-11 rounded-md px-8",
    icon: "h-10 w-10",
  }
  
  return (
    <button
      className={cn(
        // ring-offset keeps the focus ring visible against a same-coloured
        // button fill -- without it, keyboard focus on a primary button is
        // nearly invisible.
        "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className
      )}
      ref={ref}
      {...props}
    />
  )
})
Button.displayName = "Button"

export { Button }
