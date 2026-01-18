import React from "react";

export interface SidebarSectionDef {
  id: string;
  label: string;
  toggleable?: boolean;
}

interface SidebarSettingsProps {
  sectionDefs: SidebarSectionDef[];
  visibleSections: Set<string>;
  setVisibleSections: React.Dispatch<React.SetStateAction<Set<string>>>;
  showSettingsDropdown: boolean;
  setShowSettingsDropdown: (show: boolean) => void;
}

export const SidebarSettings: React.FC<SidebarSettingsProps> = ({
  sectionDefs,
  visibleSections,
  setVisibleSections,
  showSettingsDropdown,
  setShowSettingsDropdown,
}) => {
  return (
    <div className="calkit-sidebar-settings-container">
      <button
        className="calkit-sidebar-settings-btn"
        title="Show/hide categories"
        onClick={(e) => {
          e.stopPropagation();
          setShowSettingsDropdown(!showSettingsDropdown);
        }}
      >
        ⚙️
      </button>
      {showSettingsDropdown && (
        <div
          className="calkit-settings-dropdown"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          {sectionDefs
            .filter((section) => section.toggleable !== false)
            .map((section) => (
              <div
                key={section.id}
                className="calkit-settings-item"
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                <label
                  className="calkit-settings-checkbox-label"
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                >
                  <input
                    type="checkbox"
                    checked={visibleSections.has(section.id)}
                    onChange={(e) => {
                      const next = new Set(visibleSections);
                      if (e.target.checked) {
                        next.add(section.id);
                      } else {
                        next.delete(section.id);
                      }
                      setVisibleSections(next);
                    }}
                  />
                  {section.label}
                </label>
              </div>
            ))}
        </div>
      )}
    </div>
  );
};
