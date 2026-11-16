"use client"

import { Menu } from "@base-ui/react/menu"
import { cn } from "cn"

function DropdownMenu(props: Menu.Root.Props) {
  return <Menu.Root {...props} />
}

function DropdownMenuTrigger(props: Menu.Trigger.Props) {
  return <Menu.Trigger data-slot="dropdown-menu-trigger" {...props} />
}

function DropdownMenuContent({
  className,
  align = "end",
  sideOffset = 6,
  ...props
}: Menu.Popup.Props & Pick<Menu.Positioner.Props, "align" | "sideOffset">) {
  return (
    <Menu.Portal>
      <Menu.Positioner align={align} sideOffset={sideOffset} className="z-50">
        <Menu.Popup
          data-slot="dropdown-menu-content"
          className={cn(
            "min-w-48 origin-(--transform-origin) rounded-lg border bg-popover p-1 text-popover-foreground shadow-md outline-none transition-[opacity,transform] duration-100 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0",
            className
          )}
          {...props}
        />
      </Menu.Positioner>
    </Menu.Portal>
  )
}

const itemClass =
  "flex w-full cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none select-none data-highlighted:bg-muted [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground"

function DropdownMenuLinkItem({ className, ...props }: Menu.LinkItem.Props) {
  return (
    <Menu.LinkItem
      data-slot="dropdown-menu-link-item"
      className={cn(itemClass, className)}
      {...props}
    />
  )
}

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuLinkItem }
