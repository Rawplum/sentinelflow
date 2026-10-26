import {
  Bell,
  LayoutDashboard,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { useAuth } from '../../auth/useAuth'
import { APP_NAME, RULE_ID } from '../../lib/constants'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  adminOnly?: boolean
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  {
    to: '/dashboard',
    label: '仪表盘',
    icon: LayoutDashboard,
    end: true,
  },
  {
    to: '/events',
    label: '安全事件',
    icon: ShieldAlert,
  },
  {
    to: '/alerts',
    label: '告警',
    icon: Bell,
  },
  {
    to: '/audit',
    label: '操作审计',
    icon: ScrollText,
    adminOnly: true,
  },
]

export function Sidebar() {
  const { isAdmin } = useAuth()

  return (
    <aside className="sf-sidebar">
      <div className="sf-brand">
        <div className="sf-brand-mark" aria-hidden="true">
          <ShieldCheck size={22} />
        </div>
        <div>
          <div className="sf-brand-name">{APP_NAME}</div>
          <div className="sf-brand-subtitle">Security Operations</div>
        </div>
      </div>

      <nav className="sf-nav" aria-label="主导航">
        <p className="sf-nav-label">Workspace</p>
        {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `sf-nav-link${isActive ? ' is-active' : ''}`
              }
            >
              <Icon size={18} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          )
        })}
      </nav>

      <div className="sf-sidebar-footer">
        <div className="sf-sidebar-rule">
          <span className="sf-status-dot" aria-hidden="true" />
          <span>{RULE_ID} active</span>
        </div>
        <div className="sf-local-badge">LOCAL BUILD</div>
        <p>仅限本地演示环境。所有权限由后端校验。</p>
      </div>
    </aside>
  )
}
