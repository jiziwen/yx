/** 首页和灵感库共用入场流程；登录前的想法仅保存在当前页面内存。 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp, type CreativeEntry } from '../../app/context';

export function useCreationEntry() {
  const { user, login, setCreativeEntry } = useApp();
  const navigate = useNavigate();
  const [pending, setPending] = useState<CreativeEntry | null>(null);
  const enter = (entry: CreativeEntry) => {
    setCreativeEntry(entry);
    navigate(
      entry.projectId
        ? `/projects/${entry.projectId}/studio`
        : '/projects?new=1' + (entry.styleId ? '&style=' + encodeURIComponent(entry.styleId) : ''),
    );
  };
  useEffect(() => {
    if (user && pending) {
      enter(pending);
      setPending(null);
    }
  }, [user, pending]);
  return (entry: CreativeEntry) => {
    if (user) enter(entry);
    else {
      setPending(entry);
      login();
    }
  };
}
