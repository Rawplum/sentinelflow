import { SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

export function NotFoundPage() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="sf-center-page">
      <div className="sf-center-card">
        <SearchX size={34} aria-hidden="true" />
        <p className="sf-eyebrow">HTTP 404</p>
        <h1>页面不存在</h1>
        <p>请检查地址，或返回控制台继续操作。</p>
        <Link
          to={isAuthenticated ? '/dashboard' : '/login'}
          className="sf-btn sf-btn-secondary sf-btn-md"
        >
          {isAuthenticated ? '返回仪表盘' : '返回登录'}
        </Link>
      </div>
    </div>
  )
}
