<script setup lang="ts">
import { Delete, Edit, Plus, Right, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  createProject,
  deleteProject,
  listProjects,
  type Project,
  updateProject,
} from '@/api/projects'
import { formatLocalDateTime } from '@/utils/datetime'

const router = useRouter()
const { locale, t } = useI18n()

const projects = ref<Project[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingProjectId = ref<number | null>(null)
const projectTitle = ref('')
const searchKeyword = ref('')

const filteredProjects = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (!keyword) {
    return projects.value
  }
  return projects.value.filter((project) => project.title.toLowerCase().includes(keyword))
})

const isEditing = computed(() => editingProjectId.value !== null)
const dialogTitle = computed(() =>
  isEditing.value ? t('projects.editDialogTitle') : t('projects.dialogTitle'),
)

const loadProjects = async () => {
  loading.value = true
  try {
    projects.value = await listProjects()
  } catch {
    ElMessage.error(t('projects.loadError'))
  } finally {
    loading.value = false
  }
}

const openCreateDialog = () => {
  editingProjectId.value = null
  projectTitle.value = ''
  dialogVisible.value = true
}

const openEditDialog = (project: Project) => {
  editingProjectId.value = project.id
  projectTitle.value = project.title
  dialogVisible.value = true
}

const saveProject = async () => {
  const title = projectTitle.value.trim()
  if (!title) {
    ElMessage.error(t('projects.projectNamePlaceholder'))
    return
  }

  saving.value = true
  try {
    if (editingProjectId.value === null) {
      await createProject({ title })
      ElMessage.success(t('projects.createSuccess'))
    } else {
      await updateProject(editingProjectId.value, { title })
      ElMessage.success(t('projects.updateSuccess'))
    }
    dialogVisible.value = false
    await loadProjects()
  } catch {
    ElMessage.error(t('projects.saveError'))
  } finally {
    saving.value = false
  }
}

const confirmDeleteProject = async (project: Project) => {
  try {
    await ElMessageBox.confirm(
      t('projects.deleteConfirm', { title: project.title }),
      t('projects.deleteDialogTitle'),
      {
        confirmButtonText: t('projects.delete'),
        cancelButtonText: t('projects.cancel'),
        type: 'warning',
      },
    )
    await deleteProject(project.id)
    ElMessage.success(t('projects.deleteSuccess'))
    await loadProjects()
  } catch (error) {
    // Element Plus 取消确认也会进入 catch；字符串 cancel/close 不应提示为错误。
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(t('projects.deleteError'))
  }
}

const openOutline = (project: Project) => {
  void router.push({
    path: '/outline',
    query: {
      project_id: String(project.id),
    },
  })
}

const formatDate = (value: string) => {
  return formatLocalDateTime(value, locale.value)
}

onMounted(() => {
  void loadProjects()
})
</script>

<template>
  <section>
    <div class="page-header">
      <el-button type="primary" :icon="Plus" @click="openCreateDialog">
        {{ t('projects.create') }}
      </el-button>
    </div>

    <section class="project-list panel">
      <header class="project-list__toolbar">
        <div class="project-list__search">
          <el-input
            v-model="searchKeyword"
            :placeholder="t('projects.search')"
            :prefix-icon="Search"
            clearable
          />
          <el-button>{{ t('projects.searchAction') }}</el-button>
        </div>
      </header>

      <el-table
        v-if="filteredProjects.length > 0 || loading"
        v-loading="loading"
        :data="filteredProjects"
        class="project-list__table"
      >
        <el-table-column prop="title" :label="t('projects.columns.title')" min-width="220" />
        <el-table-column :label="t('projects.columns.createdAt')" min-width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('projects.columns.updatedAt')" min-width="180">
          <template #default="{ row }">
            {{ formatDate(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('projects.columns.actions')" width="260" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :icon="Right" @click="openOutline(row)">
              {{ t('projects.enterOutline') }}
            </el-button>
            <el-button type="primary" link :icon="Edit" @click="openEditDialog(row)">
              {{ t('projects.edit') }}
            </el-button>
            <el-button type="danger" link :icon="Delete" @click="confirmDeleteProject(row)">
              {{ t('projects.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-else
        class="project-list__empty"
        :description="t('projects.emptyDescription')"
      >
        <el-button type="primary" :icon="Plus" @click="openCreateDialog">
          {{ t('projects.create') }}
        </el-button>
      </el-empty>
    </section>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="420px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item :label="t('projects.projectName')" required>
          <el-input
            v-model="projectTitle"
            maxlength="255"
            show-word-limit
            :placeholder="t('projects.projectNamePlaceholder')"
            @keyup.enter="saveProject"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">
          {{ t('projects.cancel') }}
        </el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">
          {{ saving ? t('projects.saving') : isEditing ? t('projects.save') : t('projects.createPlaceholder') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.project-list {
  overflow: hidden;
}

.project-list__toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 14px;
  padding: 18px;
  border-bottom: 1px solid var(--panel-border);
}

.project-list__search {
  display: flex;
  gap: 10px;
  width: min(100%, 460px);
}

.project-list__search .el-input {
  flex: 1;
}

.project-list__table {
  width: 100%;
}

.project-list__empty {
  padding: 48px 18px 56px;
}

@media (max-width: 900px) {
  .project-list__toolbar {
    justify-content: stretch;
  }

  .project-list__search {
    width: 100%;
  }
}
</style>
