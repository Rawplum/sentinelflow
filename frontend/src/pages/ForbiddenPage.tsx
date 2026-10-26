import { ShieldX } from 'lucide-react'
import { Link } from 'react-router-dom'

export function ForbiddenPage() {
  return (
    <div className="sf-center-page">
      <div className="sf-center-card">
        <ShieldX size={34} aria-hidden="true" />
        <p className="sf-eyebrow">HTTP 403</p>
        <h1>无权限访问</h1>
        <p>当前账户没有访问此页面或执行此操作所需的角色。后端已拒绝该请求。</p>
        <Link to="/dashboard" className="sf-btn sf-btn-secondary sf-btn-md">
          返回仪表盘
        </Link>
      </div>
    </div>
  )
}
