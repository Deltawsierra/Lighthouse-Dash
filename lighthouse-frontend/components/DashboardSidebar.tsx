'use client';

import { useState, useMemo, useId, type ReactNode } from 'react';
import { Layout, Menu, Input, Popover, Radio, Spin } from 'antd';
import { TableOutlined, DatabaseOutlined, HomeOutlined, SearchOutlined, SortAscendingOutlined, LoadingOutlined, CodeOutlined } from '@ant-design/icons';
import { usePathname, useRouter } from 'next/navigation';
import { useTheme } from '~/components/ThemeProvider';
import { useTables } from '~/components/TablesProvider';

const { Sider } = Layout;

type SortOption = 'az' | 'za';

/**
 * Which view the table panel is showing.
 *
 * 'data'   -> the rows in the lkp_ table
 * 'source' -> the DDL / source for that table
 */
export type ViewMode = 'data' | 'source';

interface ViewOption {
  value: ViewMode;
  label: string;
  hint: string;
  icon: ReactNode;
}

const VIEW_OPTIONS: ViewOption[] = [
  { value: 'data', label: 'Data', hint: 'Show the table rows', icon: <TableOutlined /> },
  { value: 'source', label: 'Source', hint: 'Show the table source', icon: <CodeOutlined /> },
];

interface DashboardSidebarProps {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

function toLabel(tableName: string): string {
  return tableName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function DashboardSidebar({ collapsed, onCollapse }: DashboardSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { currentScheme } = useTheme();
  const { tableNames, tablesLoading } = useTables();
  const [searchText, setSearchText] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('az');
  const [sortOpen, setSortOpen] = useState(false);

  // Local for now -- nothing consumes it yet. When the table panel needs to
  // read it, lift this into TablesProvider (or its own ViewProvider) rather
  // than threading it down through props; the panel lives under /tables/[name]
  // and is not a child of this component.
  const [viewMode, setViewMode] = useState<ViewMode>('data');

  // Unique per instance so a second sidebar in a test render doesn't join the
  // same radio group and silently steal the selection.
  const viewGroupName = useId();

  const getSelectedKey = () => {
    if (pathname === '/') return 'home';
    return pathname.split('/').pop() || 'home';
  };

  const filteredTableItems = useMemo(() => {
    const query = searchText.toLowerCase().trim();
    let filtered = query
      ? tableNames.filter((name) => name.toLowerCase().includes(query))
      : [...tableNames];

    filtered.sort((a, b) =>
      sortOption === 'az' ? a.localeCompare(b) : b.localeCompare(a)
    );

    return filtered.map((name) => ({
      key: name,
      icon: <TableOutlined style={{ fontSize: 16 }} />,
      label: toLabel(name),
      onClick: () => router.push(`/tables/${encodeURIComponent(name)}`),
    }));
  }, [tableNames, searchText, sortOption, router]);

  const sortLabels: Record<SortOption, string> = {
    az: 'A → Z',
    za: 'Z → A',
  };

  const sortContent = (
    <div style={{ width: 180 }} data-testid="popup-sort">
      <div className="mb-2">
        <span style={{ fontWeight: 600, fontSize: 13 }}>Sort Tables</span>
      </div>
      <Radio.Group
        value={sortOption}
        onChange={(e) => { setSortOption(e.target.value); setSortOpen(false); }}
        className="flex flex-col gap-1"
      >
        <Radio value="az" data-testid="radio-sort-az"><span style={{ fontSize: 13 }}>Alphabetical A → Z</span></Radio>
        <Radio value="za" data-testid="radio-sort-za"><span style={{ fontSize: 13 }}>Alphabetical Z → A</span></Radio>
      </Radio.Group>
    </div>
  );

  const homeItem = {
    key: 'home',
    icon: <HomeOutlined style={{ fontSize: 16 }} />,
    label: 'Home',
    onClick: () => router.push('/'),
  };

  return (
    <Sider
      width={280}
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      breakpoint="lg"
      collapsedWidth={80}
      className="h-screen sticky top-0 left-0"
      style={{ background: 'var(--sidebar-bg)', borderRight: '1px solid var(--sidebar-border)' }}
      data-testid="sidebar"
      trigger={null}
    >
      {/* Logo and branding */}
      <div className="p-4 mb-2" style={{ borderBottom: '1px solid var(--sidebar-border)' }}>
        <div className="flex items-center gap-3">
          <div
            className="flex items-center justify-center w-10 h-10 rounded-lg"
            style={{ background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)', boxShadow: '0 4px 12px rgba(59, 130, 246, 0.4)' }}
          >
            <DatabaseOutlined style={{ color: 'white', fontSize: 20 }} />
          </div>
          {!collapsed && (
            <div>
              <span
                style={{
                  display: 'block',
                  margin: 0,
                  fontWeight: 600,
                  fontSize: currentScheme.fontOverride ? 12 : 16,
                  color: 'var(--sidebar-text)',
                  fontFamily: currentScheme.fontOverride ? 'var(--theme-font)' : undefined,
                  letterSpacing: currentScheme.fontOverride ? '0.03em' : undefined,
                  lineHeight: currentScheme.fontOverride ? '1.6' : undefined,
                }}
              >
                Lighthouse RDM
              </span>
              <span style={{ fontSize: 12, color: 'var(--sidebar-text-muted)' }}>Data Governance</span>
            </div>
          )}
        </div>
      </div>

      {/* Home nav */}
      <div className="px-2">
        <Menu
          mode="inline"
          selectedKeys={[getSelectedKey()]}
          items={[homeItem]}
          style={{ border: 'none', background: 'transparent' }}
          data-testid="sidebar-home-menu"
        />
      </div>

      {/* View mode toggle -- cassette transport keys.
          Real radio inputs, not buttons: the browser enforces "only one down"
          and gives arrow-key navigation and screen-reader semantics for free.
          Every visual state below is driven by CSS, no JS touches appearance. */}
      <div className={collapsed ? 'px-3 mt-2' : 'px-4 mt-2'}>
        {!collapsed && (
          <div className="mb-1">
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--sidebar-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              View
            </span>
          </div>
        )}

        <div
          className={`vt-housing${collapsed ? ' vt-collapsed' : ''}`}
          role="radiogroup"
          aria-label="Table view mode"
          data-testid="toggle-view-mode"
        >
          {VIEW_OPTIONS.map((option) => (
            <label key={option.value} className="vt-key" title={option.hint}>
              <input
                type="radio"
                className="vt-input"
                name={viewGroupName}
                value={option.value}
                checked={viewMode === option.value}
                onChange={() => setViewMode(option.value)}
                data-testid={`radio-view-${option.value}`}
              />
              {/* Order matters: the styling hangs off `.vt-input:checked + .vt-cap`. */}
              <span className="vt-cap">
                <span className="vt-led" aria-hidden="true" />
                <span className="vt-icon">{option.icon}</span>
                {!collapsed && <span className="vt-label">{option.label}</span>}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Tables section */}
      <div className="px-2 mt-1 flex flex-col" style={{ minHeight: 0, flex: 1 }}>
        {!collapsed && (
          <>
            <div className="px-4 py-2 mb-1 flex items-center justify-between">
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--sidebar-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Tables
              </span>
              {!tablesLoading && tableNames.length > 0 && (
                <span style={{ fontSize: 11, color: 'var(--sidebar-text-muted)' }}>
                  {tableNames.length}
                </span>
              )}
            </div>

            {/* Search input */}
            <div className="px-2 mb-2">
              <Input
                placeholder="Search tables..."
                prefix={<SearchOutlined style={{ color: 'var(--sidebar-text-muted)' }} />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                allowClear
                size="small"
                data-testid="input-table-search"
                style={{
                  background: 'var(--sidebar-hover)',
                  borderColor: 'var(--sidebar-border)',
                  color: 'var(--sidebar-text)',
                }}
              />
            </div>

            {/* Sort control */}
            <div className="px-3 mb-2 flex items-center">
              <Popover
                content={sortContent}
                trigger="click"
                open={sortOpen}
                onOpenChange={setSortOpen}
                placement="rightTop"
              >
                <button
                  className="flex items-center gap-1 sidebar-clickable-link"
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '2px 0',
                    fontSize: 12,
                    fontWeight: 500,
                    color: sortOption !== 'az' ? '#3b82f6' : 'var(--sidebar-text-muted)',
                    transition: 'color 0.2s',
                  }}
                  data-testid="button-sort"
                >
                  <SortAscendingOutlined style={{ fontSize: 12 }} />
                  <span style={{ textDecoration: 'underline', textUnderlineOffset: '3px' }}>Sort: {sortLabels[sortOption]}</span>
                </button>
              </Popover>
            </div>
          </>
        )}

        {/* Scrollable table list */}
        <div className="overflow-y-auto" style={{ flex: 1 }}>
          {tablesLoading ? (
            !collapsed && (
              <div className="flex items-center justify-center py-6" data-testid="spinner-tables-loading">
                <Spin indicator={<LoadingOutlined style={{ fontSize: 18, color: 'var(--sidebar-text-muted)' }} spin />} />
              </div>
            )
          ) : filteredTableItems.length > 0 ? (
            <Menu
              mode="inline"
              selectedKeys={[getSelectedKey()]}
              items={filteredTableItems}
              style={{ border: 'none', background: 'transparent' }}
              data-testid="sidebar-table-menu"
            />
          ) : (
            !collapsed && (
              <div className="px-4 py-3 text-center" style={{ color: 'var(--sidebar-text-muted)', fontSize: 13 }} data-testid="text-no-tables-found">
                {tableNames.length === 0 ? 'No tables available' : 'No tables found'}
              </div>
            )
          )}
        </div>
      </div>

      {/* Sidebar theme overrides */}
      <style jsx global>{`
        .ant-layout-sider { background: var(--sidebar-bg) !important; }
        .ant-layout-sider .ant-menu { background: transparent !important; }
        .ant-layout-sider .ant-menu-item { color: var(--sidebar-text) !important; margin: 4px 8px !important; border-radius: 8px !important; transition: all 0.2s ease !important; }
        .ant-layout-sider .ant-menu-item:hover { background: var(--sidebar-hover) !important; }
        .ant-layout-sider .ant-menu-item-selected { background: var(--sidebar-active) !important; color: #ffffff !important; }
        .ant-layout-sider .ant-menu-item-selected::after { display: none !important; }
        .ant-layout-sider .ant-menu-item .anticon { color: inherit !important; }
        .ant-layout-sider-trigger { background: var(--sidebar-hover) !important; color: var(--sidebar-text) !important; }
        .ant-layout-sider .ant-input-affix-wrapper { background: var(--sidebar-hover) !important; border-color: var(--sidebar-border) !important; }
        .ant-layout-sider .ant-input-affix-wrapper .ant-input { background: transparent !important; color: var(--sidebar-text) !important; }
        .ant-layout-sider .ant-input-affix-wrapper .ant-input::placeholder { color: var(--sidebar-text-muted) !important; }
        .ant-layout-sider .ant-input-affix-wrapper .ant-input-clear-icon { color: var(--sidebar-text-muted) !important; }
        .sidebar-clickable-link { opacity: 0.85; transition: opacity 0.2s, color 0.2s; }
        .sidebar-clickable-link:hover { opacity: 1; color: #3b82f6 !important; }

        /* ====================================================================
           View mode toggle -- cassette transport keys
           --------------------------------------------------------------------
           Four things make it read as mechanical. Change one and it stops
           feeling like a button and starts feeling like a div:

             1. The key's side wall is a box-shadow with ZERO blur, offset down
                by exactly --vt-travel. That hard edge is the moulded plastic.
                Blur it and the key becomes a floating card.
             2. Pressing translates the cap down by exactly --vt-travel while
                collapsing that wall to 0, so the face lands flush with where
                the wall's base was. The two numbers must match or the key
                looks like it is sinking through the deck.
             3. The face gradient inverts: highlight on top when up, shadow on
                top when down. That flip does most of the work.
             4. 80ms ease-out, no bounce. Transport keys snap, they do not
                spring. Past ~120ms it reads as soft-touch membrane instead.

           Colours derive from the existing --sidebar-* vars so the keys follow
           whatever theme ThemeProvider sets, without needing to know it.
           ==================================================================== */

        .vt-housing {
          --vt-travel: 3px;
          --vt-snap: 80ms;
          /* Fallbacks matter here: an undefined var inside color-mix() makes the
             whole declaration invalid, which would leave the keys unpainted. */
          --vt-well: color-mix(in srgb, var(--sidebar-bg, #1a1d23) 76%, #000);
          --vt-cap: color-mix(in srgb, var(--sidebar-hover, #2a2e36) 48%, #fff);
          --vt-cap-down: color-mix(in srgb, var(--sidebar-hover, #2a2e36) 88%, #000);
          --vt-led: #3b82f6;

          display: grid;
          grid-auto-flow: column;
          grid-auto-columns: 1fr;
          gap: 5px;
          padding: 5px;
          border-radius: 8px;
          background: linear-gradient(180deg, color-mix(in srgb, var(--vt-well) 86%, #000), var(--vt-well));
          box-shadow:
            inset 0 2px 5px rgba(0, 0, 0, 0.4),
            inset 0 -1px 0 rgba(255, 255, 255, 0.14),
            0 1px 0 rgba(255, 255, 255, 0.18);
        }

        /* Collapsed rail: stack the keys and drop the legends. The control
           stays reachable instead of disappearing like search and sort do. */
        .vt-housing.vt-collapsed {
          grid-auto-flow: row;
          grid-auto-columns: auto;
        }

        .vt-key {
          position: relative;
          display: block;
          cursor: pointer;
          /* Reserve the throw so nothing in the sidebar shifts on press. */
          padding-bottom: var(--vt-travel);
          -webkit-tap-highlight-color: transparent;
        }

        /* Hidden but still focusable and still the click target -- the <label>
           forwards the click, so the input stays in the a11y tree and tab order. */
        .vt-input {
          position: absolute;
          width: 1px;
          height: 1px;
          margin: 0;
          padding: 0;
          border: 0;
          opacity: 0;
          pointer-events: none;
        }

        .vt-cap {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 3px;
          padding: 7px 6px 6px;
          border-radius: 5px;
          background: linear-gradient(
            180deg,
            color-mix(in srgb, var(--vt-cap) 70%, #fff) 0%,
            var(--vt-cap) 40%,
            color-mix(in srgb, var(--vt-cap) 88%, #000) 100%
          );
          color: var(--sidebar-text-muted);
          box-shadow:
            0 var(--vt-travel) 0 color-mix(in srgb, var(--vt-cap) 52%, #000),
            0 calc(var(--vt-travel) + 1px) 3px rgba(0, 0, 0, 0.38);
          transform: translateY(0);
          transition:
            transform var(--vt-snap) ease-out,
            box-shadow var(--vt-snap) ease-out,
            background var(--vt-snap) ease-out,
            color var(--vt-snap) ease-out;
        }

        /* Finger down, before release -- the key follows immediately. */
        .vt-key:active .vt-cap {
          transform: translateY(var(--vt-travel));
          box-shadow:
            0 0 0 color-mix(in srgb, var(--vt-cap) 52%, #000),
            0 0 2px rgba(0, 0, 0, 0.3);
        }

        /* Latched. The browser releases the other key for us. */
        .vt-input:checked + .vt-cap {
          transform: translateY(var(--vt-travel));
          background: linear-gradient(
            180deg,
            color-mix(in srgb, var(--vt-cap-down) 90%, #000) 0%,
            var(--vt-cap-down) 70%,
            color-mix(in srgb, var(--vt-cap-down) 94%, #fff) 100%
          );
          color: var(--sidebar-text);
          box-shadow:
            0 0 0 color-mix(in srgb, var(--vt-cap) 52%, #000),
            inset 0 2px 3px rgba(0, 0, 0, 0.28),
            inset 0 -1px 0 rgba(255, 255, 255, 0.35);
        }

        .vt-input:focus-visible + .vt-cap {
          outline: 2px solid #3b82f6;
          outline-offset: 2px;
        }

        @media (hover: hover) {
          .vt-key:hover .vt-input:not(:checked) + .vt-cap {
            background: linear-gradient(
              180deg,
              color-mix(in srgb, var(--vt-cap) 60%, #fff) 0%,
              color-mix(in srgb, var(--vt-cap) 94%, #fff) 40%,
              color-mix(in srgb, var(--vt-cap) 92%, #000) 100%
            );
            color: var(--sidebar-text);
          }
        }

        .vt-led {
          width: 4px;
          height: 4px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--vt-led) 24%, #4a4a4a);
          box-shadow: inset 0 0 1px rgba(0, 0, 0, 0.6);
          transition: background var(--vt-snap) ease-out, box-shadow var(--vt-snap) ease-out;
        }

        .vt-input:checked + .vt-cap .vt-led {
          background: var(--vt-led);
          box-shadow:
            0 0 4px color-mix(in srgb, var(--vt-led) 80%, transparent),
            0 0 1px var(--vt-led);
        }

        .vt-icon .anticon { font-size: 15px; color: inherit !important; display: block; }

        .vt-label {
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.07em;
          text-transform: uppercase;
          line-height: 1;
        }

        /* The position change is the state indicator, not decoration, so it
           stays. Only the travel time goes. */
        @media (prefers-reduced-motion: reduce) {
          .vt-cap, .vt-led { transition-duration: 1ms; }
        }
      `}</style>
    </Sider>
  );
}
